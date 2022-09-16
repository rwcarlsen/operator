import inspect
from collections import defaultdict
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import yaml

import ops.model
from ops import testing
from ops.charm import SecretChangedEvent, CharmBase, SecretRotateEvent, SecretRemoveEvent
from ops.framework import EventBase, BoundEvent
from ops.model import Secret
from ops.testing import _TestingModelBackend, Harness

SECRET_METHODS = ("secret_set",
                  "secret_remove",
                  "secret_grant",
                  "secret_revoke",
                  "secret_add",
                  "secret_ids",
                  "secret_get",
                  "secret_meta")


@pytest.mark.parametrize('method', SECRET_METHODS, ids=SECRET_METHODS)
def test_testing_secrets_manager_api_completeness(method):
    # Assert that the signatures of the testing model backend's secret-methods match
    # the real backend ones.
    mmb_sig = inspect.signature(getattr(ops.model._ModelBackend, method))
    tmb_sig = inspect.signature(getattr(_TestingModelBackend, method))

    assert tmb_sig == mmb_sig, 'the _TestingModelBackend and ' \
                               '_ModelBackend signatures have diverged'


@pytest.fixture
def backend():
    import ops.charm
    meta = ops.charm.CharmMeta.from_yaml('name: testcharm', None)
    return _TestingModelBackend('testunit/0', meta, None)


@pytest.fixture
def model(backend):
    return ops.model.Model(
        ops.charm.CharmMeta({'name': 'testcharm'}),
        backend
    )

class TestCharm(CharmBase):
    pass

def test_secret_add_and_get():
    # I always have access to the secrets I created
    harness = Harness(TestCharm, meta='name: testcharm')
    sec1 = harness.add_secret('testcharm', {'foo': 'bar'}, 42)
    sec2 = harness.model.get_secret(sec1.id)
    assert sec1 == sec2


def test_cannot_get_removed_secret():
    harness = Harness(TestCharm, meta='name: testcharm')
    sec1 = harness.add_secret('testcharm', {'foo': 'bar'}, 42)

    harness.model.get_secret(sec1.id)
    sec1.remove()
    with pytest.raises(Exception):
        harness.model.get_secret(sec1.id)

def test_grant_secret(model, backend):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    backend._mock_relation_ids_map[1] = 'remote/0'
    secret.grant('remote/0',
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))

    with backend._god_mode_ctx(True):
        with pytest.raises(ops.model.ModelError):  # raised by Model, not Backend!
            secret.get('a')

        backend.secret_get(secret.id)  # this works in god mode

    with backend._god_mode_ctx(False):
        with pytest.raises(ops.model.OwnershipError):
            backend.secret_get(secret.id)


def test_cannot_get_revoked_secret(model, backend):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    backend._mock_relation_ids_map[1] = 'remote/0'
    secret.grant('remote/0',
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))
    backend.secret_revoke(secret.id, 1)

    with pytest.raises(Exception):  # todo: exceptions
        secret.get()


def test_secret_event_snapshot(backend):
    sec = Secret(backend, 'secret:1234567',
                 label='bar', revision=7, am_owner=True)
    e1 = SecretChangedEvent('', sec)
    e2 = SecretChangedEvent('', None)

    e2.framework = Mock(model=Mock(_backend=backend))
    e2.restore(e1.snapshot())
    assert e1.secret.__dict__ == e2.secret.__dict__

#def test_owner_create_secret(owner, holder):
#    sec_id = ''
#
#    @owner.run
#    def create_secret():
#        nonlocal sec_id
#        secret = owner.app.add_secret({'a': 'b'})
#        secret.set_label('my_label')
#        sec_id = secret.id
#        assert secret._am_owner
#
#        # now we can also get it by:
#        secret2 = owner.model.get_secret('my_label')
#        assert secret == secret2
#
#        # however we can't inspect the contents:
#        with pytest.raises(ops.model.OwnershipError):
#            secret.get('a')
#
#    @holder.run
#    def secret_get_without_access():
#        nonlocal sec_id
#        # labels are local: my_label is how OWNER knows this secret, not holder.
#        with pytest.raises(ops.model.InvalidSecretIDError):
#            assert holder.model.get_secret('my_label')
#
#        with pytest.raises(ops.model.SecretNotGrantedError):
#            holder.model.get_secret(sec_id)
#
#    @owner.run
#    def grant_access():
#        # simulate a relation, grant the holder access.
#        grant(owner, 'my_label', holder)
#
#    @holder.run
#    def secret_get_with_access():
#        nonlocal sec_id
#        # as a holder, we can secret-get
#        secret = holder.model.get_secret(sec_id)
#        secret.set_label('other_label')
#
#        assert not secret._am_owner
#        # we can get it by label as well now!
#        assert holder.model.get_secret('other_label') == secret
#
#        assert secret.get('a') == 'b'
#
#    @holder.run
#    def secret_relabel():
#        nonlocal sec_id
#        # as a holder, we can secret-get
#        secret = holder.model.get_secret('other_label')
#        secret.set_label('new_label')
#        secret1 = holder.model.get_secret('new_label')
#        assert secret == secret1
#        assert secret.get('a') == secret1.get('a')
#
#
#class TestHolderCharmPOV:
#    # Typically you want to unittest
#    def test_owner_charm_pov(self, owner, holder, holder_harness):
#        db_rel_id = holder_harness.add_relation('db', owner.app.name)
#        secret = holder_harness.add_secret(owner.app, {'token': 'abc123'}, db_rel_id)
#        secret.grant(holder_harness.charm.unit)
#        sec_id = secret.id
#
#        # verify that the holder can access the secret
#        @holder.run  # this is charm code:
#        def secret_get_with_access():
#            secret = holder.model.get_secret(sec_id)
#            assert not secret._am_owner
#            secret.set_label('other_label')
#            assert secret.get('token') == 'abc123'
#            assert secret.revision == 0
#
#        @holder.listener(holder.on.secret_changed)
#        def _on_changed(evt):
#            assert isinstance(evt, SecretChangedEvent)
#            # SecretRotateEvent.secret is *the currently tracked revision*
#            assert evt.secret == holder.model.get_secret(sec_id)
#            assert evt.secret.revision == 0
#
#        @holder.listener(holder.on.secret_remove)
#        def _on_remove(evt):
#            assert isinstance(evt, SecretRemoveEvent)
#            # SecretRotateEvent.secret is *the currently tracked revision*
#            assert evt.secret == holder.model.get_secret(sec_id)
#
#        # rotate the secret
#        secret.set({'token': 'new token!!'})
#        assert holder.get_calls() == [_on_changed]
#
#        # and again
#        secret.set({'token': 'yet another one'})
#        assert holder.get_calls() == [_on_changed, _on_changed]
#
#        @holder.run
#        def _update_to_latest_revision():
#            # we didn't call update() yet, so our revision is still stuck at 0
#            secret = holder.model.get_secret(sec_id)
#            assert secret.revision == 0
#            assert secret.get('token') == 'abc123'
#
#            new_secret = secret.update()
#            assert new_secret.revision == 2
#            assert new_secret.get('token') == 'yet another one'
#
#        secret.prune_all_untracked()  # removes 0 and 1
