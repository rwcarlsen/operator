
import model
import charm

class SecretRemoveEvent():
    def __init__(self, ...):
        # note that revision is set to now-obsolete secret revision (that can be removed)
        self.secret = Secret(..., revision=)

class Secret:
    def __init__(self, label, *keysvals):
        ...
        self.label = label
        self.uri = ... # one per label
        self._revision = ... # many per label/uri

    def update(self, keysvals):
        if not self._own_secret and len(keysvals) > 0:
            raise RuntimeError("you can't do that")

        if len(keysvals) == 0:
            self._model.secret_get(self._uri, update=True)
            return

        self._model.secret_update(self._uri, keysvals)

    def grant(self, relation, unit=None): # grants entire remote app if unit is None
        ...

    def prune(self, revision):
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model.secret_remove(self._uri, revision=revision)
    # or
    def prune(self):
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model.secret_remove(self._uri, revision=self._revision)

    def remove(self):
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        self._model.secret_remove(self._uri)

    def __getitem__(self, key):
        # Load this on-demand - we don't want juju to mark our unit as tracking this secret unless the
        # charm actually accesses/uses it.  Also maybe don't cache the actual secret - helps
        # avoid accidentally logging, serializing, etc.
        return self._retrieve_the_secret(key)

class MyDbCharm(CharmBase):
    def __init__(self):

    def _on_foo_relation_created(self, event):
        # consider restricting secret creation to only the leader (at least initially - possibly
        # relax later
        if self.is_leader():
            # Or do we want an explicit grant?  I'm not sure I like the feel of requiring "secret.grant(event.app)"
            secret = self.app.add_secret('foo', 'user', 'u0', 'pass', 'p0')

            secret.grant(event.relation, event.unit)
            # or
            secret.grant(event=event) # pull context from event - seems to be ripe for confusion in relation joined vs created.
            # or
            secret.grant() # pull context from environment somehow

            # We could also auto-add the secret to the relation data in grant... convenient, but too magic?
            event.relation.data[self.app]['login-secret'] = secret # auto-convert this to the secret uri/id behind the scenes

    def _on_foo_relation_joined(self, event):
        if self.is_leader():
            # Or do we want an explicit grant?  I'm not sure I like the feel of requiring "secret.grant(event.app)"
            secret = self.app.add_secret('foo', 'user', 'u0', 'pass', 'p0')

            secret.grant(event.relation, event.app)
            # or
            secret.grant(event=event) # pull context from event
            # or
            secret.grant() # pull context from environment somehow

            # We could also auto-add the secret to the relation data in grant... convenient, but too magic?
            event.relation.data[self.app]['login-secret'] = secret # auto-convert this to the secret uri/id behind the scenes

    # sent to secret creator/owner when the secret is due to be updated/rotated.
    def _on_secret_rotate(self, event):
        event.secret.update('user', 'u1', 'pass', 'p1')

    # sent to secret creator/owner when secret is expired. Called repeatedly until the secret is removed.
    def _on_secret_expired(self, event):
        event.secret.prune()
        # or
        event.secret.prune(event.secret_revision)

        event.secret.update('user', 'u1', 'pass', 'p1')

    # sent to creator/owner when all secret consuming/reading units have called secret-get --update,
    # allowing the charm to remove obsolete secret revisions.
    def _on_secret_remove(self, event):
        event.secret.prune() # have secret pointed implicitly with the removable revision
        # or
        event.secret.prune(event.secret_revision)

        # what does this do now?
        print(event.secret['user'])

class MyOtherCharm(charm.CharmBase):
    def __init__(self):
        self._conn = self._connect_db()

    def _connect_db(self):
        ####### for unit-scoped secret ######
        label = self.unit.name + '-login-secret'
        ####### for app-scoped secret ######
        label = 'login-secret'

        rel = self.model.get_relation('foo'):
        if rel and (label in rel.data[rel.app]):
            secret = self.get_secret(rel.data[rel.app][label])
            return self._open_conn(self._db_addr, secret['user'], secret['pass']
        return None
    # or, we could provide a syntactic sugar for retrieving a secret:
    def _connect_db(self):
        secret = self.app.get_secret('foo', self.unit.name + '-login-secret') # args: relation-name, secret-label
        return self._open_conn(self._db_addr, secret['user'], secret['pass']) if secret else None

    # sent to all units that have ever read the secret value when the secret gets a new revision (i.e. is updated).
    def _secret_changed(self, event):
        event.secret.update()
        self._conn = self._connect_db()

