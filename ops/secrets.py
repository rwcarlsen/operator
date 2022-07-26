

# secret-get provides the latest revision on first call, and the same, pinned revision for following calls.

# secrets have an identifying label and consist of key-value pairs.

# Secrets have an application-default lifetime.  But can optionally be set to be scoped to a unit-lifetime or a relation-lifetime

# Access to each secret is granted within a particular relation to either an entire application or to a particular unit.
#     - granting access defaults to any unit on the remote side of the current context if one exists (i.e. in a relation-joined event context)
#       or to an entire application if in that sort of context (i.e. in a relation-joined event context)

import model
import charm


class RelationCreatedEvent():
    def add_secret(label, *keysvals, expires=None, rotate=None):
        ...
        secret = Secret(label, keysvals)
        secret.grant(self.app)
        return secret

class RelationJoinedEvent():
    def add_secret(label, *keysvals, expires=None, rotate=None):
        ...
        secret = Secret(label, keysvals)
        secret.grant(self.unit)
        return secret

class SecretRemovedEvent():
    def __init__(self, ...):
        # note that revision is set to now-obsolete secret revision (that can be removed)
        self.secret = Secret(..., revision=)

class Secret:
    def __init__(self, label, *keysvals):
        ...
        self.label = label
        self.uri = ... # one per label
        self.revision = ... # many per label/uri

    def update(self, keysvals):
        if not self._own_secret and len(keysvals) > 0:
            raise RuntimeError("you can't do that")

        if len(keysvals) == 0:
            self._model.secret_get(self._uri, update=True)
            return

        self._model.secret_update(self._uri, keysvals)

    def grant(self, entity): # entity is app or unit
        ...

    def remove(self, all=False): # all=True removes the entire secret and all revisions
        if not self._own_secret:
            raise RuntimeError("you can't do that")
        rev = ALL_REVISIONS if all else self.revision
        self._model.secret_remove(self._uri, revision=rev)

    def __getitem__(self, key):
        # Load this on-demand - we don't want juju to mark our unit as tracking this secret unless the
        # charm actually accesses/uses it.  Also maybe don't cache the actual secret - helps
        # avoid accidentally logging, serializing, etc.
        return self._retrieve_the_secret(key)

class MyDbCharm(CharmBase):
    def __init__(self):

    def _on_foo_relation_created(self, event):
        if self.is_leader():
            secret = event.add_secret('login-secret', 'user', 'u0', 'pass', 'p0') # grants entire application access
            # Or do we want an explicit grant?  I'm not sure I like the feel of requiring "secret.grant(event.app)"

            # We could also auto-add the secret to the relation data here... convenient, but more magic...
            event.relation.data[self.app]['login-secret'] = secret # auto-convert this to the secret uri/id behind the scenes

    def _on_foo_relation_joined(self, event):
        if self.is_leader():
            label = self.event.unit.name + '-login-secret'
            secret = event.add_secret(label, 'user', self.event.unit.name, 'pass', self._genpass(event.unit)) # grants only the joining unit access
            event.relation.data[self.app][label] = secret # auto-convert this to the secret uri?

    def _on_foo_relation_changed(self, event):
        # backup in case we missed a relation created or joined for some reason
        label = self.event.unit.name + '-login-secret'
        if self.is_leader() and label not in event.relation.data[self.app]:
            label = self.event.unit.name + '-login-secret'
            secret = event.add_secret(label, 'user', self.event.unit.name, 'pass', self._genpass(event.unit)) # grants only the joining unit access
            event.relation.data[self.app][label] = secret # auto-convert this to the secret uri?

    # sent to secret creator/owner when the secret is due to be updated/rotated.
    def _on_secret_rotate(self, event):
        self._regen_secret(event.secret, ...)

    # sent to secret creator/owner when secret is expired. Called repeatedly until the secret is removed.
    def _on_secret_expired(self, event):
        event.secret.remove()
        self._regen_secret(event.secret, ...)

    # sent to creator/owner when all secret consuming/reading units have called secret-get --update,
    # allowing the charm to remove obsolete secret revisions.
    def _on_secret_removeed(self, event):
        event.secret.remove()

    def _regen_secret(self, secret, ...):
        ...
        secret.update('user', 'u1', 'pass', 'p1')

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

    # alternatively, we could provide a syntactic sugar for retrieving a secret:
    def _connect_db(self):
        secret = self.model.get_secret('foo', self.unit.name + '-login-secret') # args: relation-name, secret-label
        return self._open_conn(self._db_addr, secret['user'], secret['pass']) if secret else None

    # sent to all units that have ever read the secret value when the secret gets a new revision (i.e. is updated).
    def _secret_changed(self, event):
        event.secret.update()
        self._conn = self._connect_db()

