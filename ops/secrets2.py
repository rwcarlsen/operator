
import model
import charm

class SecretRemoveEvent():
    def __init__(self, ...):
        # note that revision is set to now-obsolete secret revision (that can be removed)
        self.secret = Secret(..., revision=)

class SecretRotateEvent():
    def __init__(self, ...):
        self.secret = Secret(...)

class SecretExpired():
    def __init__(self, ...):
        self.secret = Secret(...)

class SecretChangedEvent():
    def __init__(self, ...):
        self.secret = Secret(...)

class Secret:
    def __init__(self, uri, relation=None, label=None, revision=None):
        self.uri = uri
        self.label = label
        self.relation_name = relation
        self._revision = revision

    def update(self, **keysvals):
        """
        If you are the secret creator, update the secret to a new revision with the data from
        keysvals, otherwise takes no arguments and updates to provide the latest revision of the
        secret.
        """
        if not self._own_secret and len(keysvals) > 0:
            raise RuntimeError("you can't do that")

        if len(keysvals) == 0:
            self._model._backend.secret_get(self._uri, label=self.label, update=True)
            return

        self._model._backend.secret_update(self._uri, keysvals)

    def grant(self, relation, unit=None): # grants entire remote app if unit is None
        """
        grants access to this secret over the specified to either the entire remote application
        (the default) or to the given unit if one is provided.
        """
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model._backend.secret_grant(self._uri, relation, unit=unit)
        ...

    # Not sure which approach to take:
    def prune(self, revision): # explicit revision removal
        """Remove the specified secret revision."""
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model._backend.secret_remove(self._uri, revision=revision)
    def prune(self): # implicit removal of the revision the secret is "tracking" under the hood
        """Remove the revision the secret represents."""
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model._backend.secret_remove(self._uri, revision=self._revision)

    def remove(self):
        """Remove the entire secret - all revisions."""
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model._backend.secret_remove(self._uri)

    def __getitem__(self, key):
        # Load this on-demand - we don't want juju to mark our unit as tracking this secret unless the
        # charm actually accesses/uses it.  Also maybe don't cache the actual secret - helps
        # avoid accidentally logging, serializing, etc.
        return self._model._backend.secret_get(self._uri, key)

class Application:
    def add_secret(self, label, expire=None, rotate=None, **keysvals):
        self._model._backend.secret_add(label, expire, rotate, keysvals)
    def get_secret(self, sec_id, label):
        ...
        s = Secret(..., label=label, ...)
        s.update()
        return s

class MyDbCharm(CharmBase):
    def __init__(self):
        # TODO: if we create a global secret, where does the app store/remember it?
        secret = self.app.add_secret(...)
        # ???

    def _on_foo_relation_created(self, event):
        if self.is_leader():
            label = 'foo-login'
            secret = self.app.add_secret(label, 'user', 'u0', 'pass', 'p0')

            # grant entire remote app access
            secret.grant(event.relation, set_key=label) # optionally auto-set relation data secret id field here
            # or manually set via separate call:
            event.relation.data[self.app][label] = secret # auto-convert this to the secret uri/id behind the scenes

    def _on_foo_relation_joined(self, event):
        if self.is_leader():
            label = 'foo-login-' + event.unit.name
            secret = self.app.add_secret(label, 'user', 'u0', 'pass', 'p0')

            # grant one remote unit access
            secret.grant(event.relation, unit=event.unit, set_key=label) # optionally auto-set relation data secret id field here
            # or manually set via separate call:
            event.relation.data[self.app][label] = secret # auto-convert this to the secret uri/id behind the scenes

    # sent to secret creator/owner when the secret is due to be updated/rotated.
    def _on_secret_rotate(self, event):
        s = event.secret
        if s.label == 'foo-login':
            ...
            s.update('user', 'u1', 'pass', 'p1')
        elif s.label == 'bar-login':
            ...

    # sent to secret creator/owner when secret is expired. Called repeatedly until the secret is removed.
    def _on_secret_expired(self, event):
        event.secret.prune()
        if s.label == 'foo-login':
            ...
        elif s.label == 'bar-login':
            ...

    # sent to creator/owner when all secret consuming/reading units have called secret-get --update,
    # allowing the charm to remove obsolete secret revisions.
    def _on_secret_remove(self, event):
        event.secret.prune()
        # TODO: what does this do now (after pruning)?
        print(event.secret['user'])

        if s.label == 'foo-login':
            ...
        elif s.label == 'bar-login':
            ...

# consumer manual
class MyOtherCharm(charm.CharmBase):
    def _on_foo_relation_changed(self, event):
        rel = event.relation
        if 'foo-login' in rel.data[rel.app] and self._db_conn is None:
            sec_id = rel.data[rel.app]['foo-login']
            secret = self.app.get_secret(sec_id, 'my-foo-login-label')
            self._on_foo_login_changed(secret)
        ...

    def _on_baz_relation_changed(self, event):
        rel = event.relation
        if 'bar-login' in rel.data[rel.app] and not self._bar_initialized:
            sec_id = rel.data[rel.app]['bar-login']
            secret = self.app.get_secret(sec_id, 'my-bar-login-label')
            self._on_bar_login_changed(secret)
        ...


    def _on_secret_changed(self, event):
        event.secret.update()
        if event.secret.label == 'my-foo-login-label':
            self._on_foo_login_changed(event.secret)
        elif event.secret.label == 'my-bar-login-label':
            self._on_bar_login_changed(event.secret)
        ...

    def _on_foo_login_changed(self, secret):
        secret.update() # need to set secret to track latest revision
        self._db_conn = self._connect_db(secret)
        ...

# consumer auto
class RelationSecretWatcher:
    def __init__(self, charm, key, hook, is_initialized):
        self.charm = charm
        self._key = key
        self._hook = hook
        self._is_initialized = is_initialized
        # We don't want to re-run secret hook tracking and init if we are already tracking the secret.
        # Ideally we could know if/when the secret key was added to relation data and
        # automatically handle/skip this without the user providing us a function to call.
        # "secret-granted" event anyone?  Otherwise, user needs to use e.g. workload state or some
        # manually persisted state to know if we need to reinit - this is what is_initialized needs
        # to tell us.
    def _on_relation_changed(self, event):
        rel = event.relation
        label = self.charm._secret_label(rel.name, self._key)
        if self._key not in rel.data[rel.app]:
            return
        if self._is_initialized():
            return

        sec_id = rel.data[rel.app][self._key]
        secret = self.charm.app.get_secret(sec_id, label)
        self._hook(secret)
class CharmBase:
    def __init__(self):
        self._secret_hooks = {}
        self._secret_relations = set()

    def _secret_label(self, relation_name, key):
        return 'secret-{}-{}'.format(relation_name, key)

    # is_initialized is a func that returns a bool - True if the secret has already been
    # initialized in the charm and is already being tracked.
    def observe_secret(relation_name, key, hook, is_initialized):
        # auto-construct label
        label = self._secret_label(relation_name, key)
        self._secret_hooks[label] = hook
        if len(self._secret_hooks) == 0:
            self.observe(self.on.secret_changed, self._on_secret_changed)
        self.observe(self.on[relation_name].relation_changed, RelationSecretWatcher(self, key, hook, is_initialized))

    def _on_secret_changed(self, event):
        event.secret.update()
        self._secret_hooks[event.secret.label](event.secret)
class MyOtherCharm(charm.CharmBase):
    def __init__(self):
        ...
        self.app.observe_secret('the-relation', 'foo-login', self._connect_db, self._db_connected)

    def _db_connected(self):
        ...
        return connected

    def _connect_db(self, secret):
        ...

