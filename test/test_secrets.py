import inspect
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import yaml

import ops.model
from ops import testing
from ops.charm import CharmBase, SecretChangedEvent, SecretRemoveEvent
from ops.framework import BoundEvent, EventBase
from ops.model import _Secret
from ops.testing import Harness, _TestingModelBackend

SECRET_METHODS = ("secret_set",
                  "secret_remove",
                  "secret_grant",
                  "secret_revoke",
                  "secret_add",
                  "secret_ids",
                  "secret_get")


@pytest.mark.parametrize('method', SECRET_METHODS, ids=SECRET_METHODS)
def test_testing_secrets_manager_api_completeness(method):
    # Assert that the signatures of the testing model backend's secret-methods match
    # the real backend ones.
    mmb_sig = inspect.signature(getattr(ops.model._ModelBackend, method))
    tsm_sig = inspect.signature(getattr(testing._TestingSecretManager, method))
    tmb_sig = inspect.signature(getattr(_TestingModelBackend, method))

    assert tsm_sig == mmb_sig, 'the _TestingSecretManager and ' \
                               '_ModelBackend signatures for {} have diverged'.format(method)
    assert tmb_sig == mmb_sig, 'the _TestingModelBackend and ' \
                               '_ModelBackend signatures for {} have diverged'.format(method)


class _TestingSecretManager(testing._TestingSecretManager):
    """Allows testing the secrets manager in isolation."""

    def __init__(self, this_unit: str, _god_mode: bool = False):
        super().__init__(this_unit, None)
        self._god_mode = _god_mode
        self._backend = Mock(_relation_ids_map=self._mock_relation_ids_map)
        self._is_leader = False

    @property
    def is_leader(self):
        # allows to mock leadership
        return self._is_leader

    def relation_list(self, relation_id):
        # allows to pass this manager as _ModelBackend so far as Relations are concerned
        try:
            return self._mock_relation_ids_map[relation_id]
        except KeyError as e:
            raise model.RelationNotFoundError from e

    @property
    def _hook_is_running(self) -> bool:
        # used to switch the backend between
        #   'god mode' -> no permission checks and all
        #   'charm mode' -> permission checks enforced!
        #       the backend will behave as a 'real' backend would.
        return not self._god_mode

    @contextmanager
    def _god_mode_ctx(self, value: bool = True):
        """Do temporarily as if you have power, or not."""
        gm = self._god_mode
        self._god_mode = value
        yield
        self._god_mode = gm


def bind_secret_mgrs(mgr1: _TestingSecretManager, mgr2: _TestingSecretManager):
    """Make the two managers aware of one another, allowing us to simulate grant/revoke."""
    mgr1._bind(mgr2)  # noqa
    mgr2._bind(mgr1)  # noqa


def bind(owner_harness: Harness, holder_harness: Harness):
    # binds the two harnesses in such a way that the respective Secret
    # backends will work in sync
    bind_secret_mgrs(owner_harness.model._backend._secrets, holder_harness.model._backend._secrets)  # noqa


@pytest.fixture
def backend():
    return _TestingSecretManager('myapp/0')


@pytest.fixture
def model(backend):
    return ops.model.Model(
        ops.charm.CharmMeta({'name': 'myapp'}),
        backend
    )


def assert_secrets_equal(s1: _Secret, s2: _Secret):
    if s1._am_owner and s2._am_owner:  # noqa
        if not s1.revision == s2.revision:
            return False
    return (s1.id, s1.label) == (s2.id, s2.label)


def test_secret_add_and_get(model, backend):
    secret = model.unit.add_secret({'foo': 'bar'}, label='hey!')
    # I always have access to the secrets I created
    with backend._god_mode_ctx(value=False):
        secret_2 = model.get_secret(id=secret.id)
    assert_secrets_equal(secret, secret_2)


def test_secret_get_by_label_owner(model, backend):
    secret = model.unit.add_secret({'foo': 'bar'}, label='hey!')
    secret2 = model.get_secret(label='hey!')
    assert_secrets_equal(secret, secret2)


def test_secret_get_by_id_owner(model, backend):
    secret = model.unit.add_secret({'foo': 'bar'}, label='hey!')
    secret2 = model.get_secret(id=secret.id)
    assert_secrets_equal(secret, secret2)


@pytest.mark.parametrize('god_mode', (True, False))
@pytest.mark.parametrize('owner', ('unit', 'application'))
@pytest.mark.parametrize('leader', (True, False))
def test_cannot_get_removed_secret(model, god_mode, leader, owner, backend):
    backend._is_leader = leader

    # we create a secret and then remove it.
    with backend._god_mode_ctx():
        secret_id = backend.secret_add(content={'foo': 'bar'}, owner=owner)
        backend.secret_remove(id=secret_id)

    with backend._god_mode_ctx(value=god_mode):
        # god mode or not, if a secret is gone, it's gone.
        with pytest.raises(ops.model.InvalidSecretIDError):
            model.get_secret(id=secret_id)


def test_duplicate_labels_raise(model):
    _ = model.unit.add_secret({'foo': 'bar'}, label='foo')

    with pytest.raises(Exception):  # todo: exceptions
        _ = model.unit.add_secret({'another': 'secret'}, label='foo')

    with pytest.raises(Exception):  # todo: exceptions
        _ = model.app.add_secret({'another': 'secret'}, label='foo')


@pytest.mark.parametrize('god_mode', (True, False))
def test_grant_secret(model, backend, god_mode):
    backend._is_leader = True

    secret = model.unit.add_secret({'foo': 'bar'}, label='hey')
    backend._mock_relation_ids_map[1] = 'remote/0'
    secret.grant(model.get_unit('remote/0'),
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))

    # as an owner, I can see my own secret values
    with backend._god_mode_ctx(god_mode):
        assert secret.get('foo') == 'bar'
        assert backend.secret_get(secret.id) == {'foo': 'bar'}


def test_cannot_get_revoked_secret(model, backend):
    backend._is_leader = True

    secret = model.unit.add_secret({'foo': 'bar'})
    backend._mock_relation_ids_map[1] = 'remote/0'
    secret.grant(model.get_unit('remote/0'),
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))
    backend.secret_revoke(secret.id, 1)

    remote_0_mgr = _TestingSecretManager('remote/0')
    bind_secret_mgrs(remote_0_mgr, backend)

    # if remote_0 tried to get the secret:
    with pytest.raises(ops.model.SecretNotGrantedError):
        remote_0_mgr.secret_get(id=secret.id, key='foo')

    with pytest.raises(ops.model.SecretNotGrantedError):
        remote_0_mgr.secret_get(id=secret.id)


def test_secret_event_snapshot(backend):
    sec = _Secret(backend, 'secret:1234567',
                  label='bar', revision=7, am_owner=True)
    e1 = SecretChangedEvent('', sec)
    e2 = SecretChangedEvent('', None)

    e2.framework = Mock(model=Mock(_backend=backend))
    e2.restore(e1.snapshot())
    assert e1.secret.__dict__ == e2.secret.__dict__


def charm_type():
    class InvokeEvent(EventBase):
        pass

    class SecretTesterCharm(CharmBase):
        def __init__(self, framework, key=None):
            super().__init__(framework, key)
            self._callback = None
            self.on.define_event('invoke', InvokeEvent)
            self.framework.observe(self.on.invoke, self._on_invoke)

            self._listeners = {}
            self._listener_calls = []

        def get_calls(self, clear=False):
            calls = self._listener_calls
            if clear:
                self._listener_calls = []
            return calls

        def run(self, fn):
            if self._callback:
                raise RuntimeError('already in a run scope')

            self._callback = fn
            self._invoke()
            self._callback = None

        def _invoke(self):
            self.on.invoke.emit()

        def _on_invoke(self, event):
            self._callback()

        def listener(self, event: str):
            def wrapper(callback):
                self.register_listener(event, callback)
                return callback
            return wrapper

        def register_listener(self, event: BoundEvent, callback):
            self._listeners[event.event_kind] = callback
            self.framework.observe(event, self._call_listener)

        def _call_listener(self, evt: EventBase):
            listener = self._listeners[evt.handle.kind]
            self._listener_calls.append(listener)
            listener(evt)

    return SecretTesterCharm


@pytest.fixture(scope='function')
def owner_harness():
    return Harness(charm_type(), meta=yaml.safe_dump({'name': 'owner'}))


@pytest.fixture(scope='function')
def owner(owner_harness):
    owner_harness.begin()
    return owner_harness.charm


@pytest.fixture(scope='function')
def holder_harness():
    return Harness(charm_type(), meta=yaml.safe_dump(
        {'name': 'holder',
         'requires': {'db': {'interface': 'db'}}}))


@pytest.fixture(scope='function')
def holder(holder_harness, owner_harness):
    holder_harness.begin()
    bind(owner_harness, holder_harness)
    return holder_harness.charm


def grant(owner: CharmBase, holder: CharmBase,
          label: str = None,
          secret_id: str = None,
          relation_name='db',
          relation_id=1,
          is_peer=False):
    # simulate a relation
    owner.model._backend._secrets._mock_relation_ids_map[1] = holder.unit.name
    holder.model._backend._secrets._mock_relation_ids_map[1] = owner.unit.name

    owner.model.get_secret(label=label, id=secret_id).grant(
        holder.unit,
        relation=ops.model.Relation(relation_name, relation_id, is_peer=is_peer,
                                    backend=owner.model._backend,
                                    cache=owner.model._cache,
                                    our_unit=owner.model.unit))


def test_owner_create_secret(owner_harness, owner, holder):
    # this secret id will in practice be shared via relation data.
    # here we don't care about how it's being shared.
    sec_id = ''

    owner_harness.set_leader(True)

    @owner.run
    def create_secret():
        nonlocal sec_id
        secret = owner.app.add_secret({'foo': 'bar'}, label='my_label')
        sec_id = secret.id
        assert secret._am_owner

        # now we can also get it by:
        secret2 = owner.model.get_secret(label='my_label')
        assert_secrets_equal(secret, secret2)

        # as owners, we can inspect the contents:
        assert secret.get('foo') == 'bar'
        # and we know the revision
        assert secret.revision == 0

    @holder.run
    def secret_get_without_access():
        nonlocal sec_id
        # labels are local: my_label is how OWNER knows this secret, not holder.
        with pytest.raises(ops.model.InvalidSecretLabelError):
            assert holder.model.get_secret(label='my_label')

        # and either way, we haven't been granted the secret yet!
        with pytest.raises(ops.model.SecretNotGrantedError):
            holder.model.get_secret(id=sec_id)

    @owner.run
    def grant_access():
        # simulate a relation, grant the holder access.
        grant(owner, holder, label='my_label')

    @holder.run
    def secret_get_with_access():
        nonlocal sec_id
        # as a holder, we can secret-get
        secret = holder.model.get_secret(id=sec_id, label='other_label')

        assert not secret._am_owner
        # we can get it by label as well now!
        secret2 = holder.model.get_secret(label='other_label')
        assert_secrets_equal(secret, secret2)

        assert secret.get('foo') == 'bar'

    @holder.run
    def secret_relabel():
        nonlocal sec_id
        # as a holder, we can secret-get. If we do this outside of a secret-event context,
        # we can't map ids to labels.
        secret = holder.model.get_secret(id=sec_id, label='other_label')
        secret1 = holder.model.get_secret(id=sec_id, label='new_label')
        assert_secrets_equal(secret, secret1)
        assert secret.get("foo") == secret1.get("foo")


class TestHolderCharmPOV:
    # Typically you want to unittest
    def test_owner_charm_pov(self, owner, holder, owner_harness, holder_harness):
        rev_0_key = 'a'
        rev_1_key = 'a1'
        rev_2_key = 'a2'
        owner_harness.set_leader(True)

        db_rel_id = holder_harness.add_relation('db', owner.app.name)
        secret = holder_harness.add_secret(owner.app, {'token': rev_0_key}, db_rel_id)
        secret.grant(holder_harness.charm.unit)
        sec_id = secret.id

        # verify that the holder can access the secret
        @holder.run  # this is charm code:
        def secret_get_with_access():
            s = holder.model.get_secret(id=sec_id, label='other_label')
            assert not s._am_owner
            assert s.get('token') == rev_0_key
            # assert secret.revision == 0  # non-owners cannot see the revision

        @holder.listener(holder.on.secret_changed)
        def _on_changed(evt):
            assert isinstance(evt, SecretChangedEvent)
            # SecretRotateEvent.secret is *the currently tracked revision*
            assert_secrets_equal(evt.secret, holder.model.get_secret(id=sec_id))
            assert evt.secret.get('token') == rev_0_key

        @holder.listener(holder.on.secret_remove)
        def _on_remove(evt):
            assert isinstance(evt, SecretRemoveEvent)
            # SecretRotateEvent.secret is *the currently tracked revision*
            assert evt.secret == holder.model.get_secret(id=sec_id)

        # rotate the secret
        secret.set({'token': rev_1_key})
        assert holder.get_calls() == [_on_changed]

        # and again
        secret.set({'token': rev_2_key})
        assert holder.get_calls() == [_on_changed, _on_changed]

        @holder.run
        def _update_to_latest_revision():
            # we didn't call update() yet, so our revision is still stuck at 0
            secret = holder.model.get_secret(id=sec_id)
            assert secret.get('token') == rev_0_key

            # updating bumps us to rev2
            new_secret = secret.update()
            assert new_secret.get('token') == rev_2_key

        @owner.run  # this is charm code:
        def bump_revisions():
            s = owner.model.get_secret(id=sec_id)
            for i in range(4):
                s.set({'token': 'new_secret_rev-{}'.format(i)})

        # we just created a few extra revisions. We're tracking #2, but the backend
        # knows that there's 4 new revisions.
        # if we prune all untracked revisions (something we can only do from test code!!)
        # we will remove #0,1 and #3-5.  #6, being the latest, remains alive because the next time
        # the holder updates, that's what he'll be bumped to.

        secret.prune_all_untracked()
        secrets_mgr = secret._mgr
        for revision in (0, 1, 3, 4, 5):
            assert secrets_mgr._get_content(sec_id, revision) == secrets_mgr.RETRACTED

        @holder.run
        def _update_to_latest_revision_once_more():
            secret = holder.model.get_secret(id=sec_id)
            assert secret.get('token') == rev_2_key

            # updating bumps us to rev6
            new_secret = secret.update()
            assert new_secret.get('token') == 'new_secret_rev-3'


def test_app_scope_leader():
    mgr1 = _TestingSecretManager('local/0')
    mgr2 = _TestingSecretManager('remote/0')

    bind_secret_mgrs(mgr1, mgr2)
    mgr1._is_leader = True
    mgr1.secret_add({'abc': 'def'}, owner='application')


def test_app_scope_follower():
    mgr1 = _TestingSecretManager('local/0')
    mgr1._is_leader = False

    with pytest.raises(ops.model.SecretOwnershipError):
        mgr1.secret_add({'abc': 'def'}, owner='application')

    # we give it leadership to create a secret
    mgr1._is_leader = True
    secret_id = mgr1.secret_add({'abc': 'def'}, owner='application')

    # but then we lose leadership again
    mgr1._is_leader = False

    # and we can't do any management on this secret:
    with pytest.raises(ops.model.SecretOwnershipError):
        mgr1.secret_set(secret_id, content={'foo': 'bar'})
    with pytest.raises(ops.model.SecretOwnershipError):
        mgr1.secret_remove(secret_id)
    with pytest.raises(ops.model.SecretOwnershipError):
        mgr1.secret_grant(secret_id, 0, 'anything/0')
