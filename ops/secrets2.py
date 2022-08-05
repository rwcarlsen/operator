
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
            self._model._backend.secret_get(self._uri, update=True)
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

class MyDbCharm(CharmBase):
    def __init__(self):
        # TODO: if we create a global secret, where does the app store/remember it?
        secret = self.app.add_secret(...)
        # ???

    def _on_foo_relation_created(self, event):
        if self.is_leader():
            # create an remote-application access level secret
            label = 'foo-login'
            secret = self.app.add_secret(label, 'user', 'u0', 'pass', 'p0')
            secret.grant(event.relation)
            event.relation.data[self.app][label] = secret # auto-convert this to the secret uri/id behind the scenes

    def _on_foo_relation_joined(self, event):
        if self.is_leader():
            # Or do we want an explicit grant?  I'm not sure I like the feel of requiring "secret.grant(event.app)"
            label = 'foo-login-' + event.unit.name +
            secret = self.app.add_secret(label, 'user', 'u0', 'pass', 'p0')
            secret.grant(event.relation, unit=event.unit)
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
        s = event.secret
        if s.label == 'foo-login':
            ...
            event.secret.prune()
        elif s.label == 'bar-login':
            ...

    # sent to creator/owner when all secret consuming/reading units have called secret-get --update,
    # allowing the charm to remove obsolete secret revisions.
    def _on_secret_remove(self, event):
        s = event.secret
        if s.label == 'foo-login':
            ...
            event.secret.prune()

            # TODO: what does this do now (after pruning)?
            print(event.secret['user'])
        elif s.label == 'bar-login':
            ...

class Framework:
    def __init__(self):
        # {relation_name: [data_key, ...], ...}
        self._secrets_map = {}

        self._secret_hooks = {}

    def observe_secret(self, relation_name, secret_label, hook):
        if relation_name not in self._secret_hooks:
            self._secret_hooks[relation_name] = {}
        self._secret_hooks[relation_name][secret_label] = hook

        self.observe(self.on.secret_changed, self._on_secret_changed)

    def _on_secret_changed(self, event):
        # determine and store the mapping between secret ids and
        rel = event.secret.relation_name
        if rel in self._secret_hooks:
            label = event.secret.label
            if label in self._secret_hooks[rel]:
                hook = self._secret_hooks[rel][label]
                hook(event)

class MyOtherCharm(charm.CharmBase):
    def __init__(self):
        self._conn = self._connect_db()

        self._secret_hooks = {}

        # args are <relation-name>, <relation-data-key>, <hook-function>
        self.framework.observe_secret('db-relation', 'foo-login', _on_foo_login_changed)

    def _on_foo_relation_changed(self, event):
        self._ensure_connected()

    def _on_foo_login_changed(self, event):
        # TODO: should these be deferrable?
        event.secret.update() # need to set secret to track latest revision
        self._db_conn = self._connect_db(self, event.secret)

    def _on_something_else(self, event):
        if not self._ensure_connected():
            event.defer()
        ...

    def _ensure_connected(self):
        rel = self.model.get_relation('db-relation')
        if 'foo-login' in rel.data[rel.app] and self._db_conn is None:
            sec_id = rel.data[rel.app]['foo-login']
            self._db_conn = self._connect_db(self.get_secret(sec_id))

    def _connect_db(self, secret):
        ...

