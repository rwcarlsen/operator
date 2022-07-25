

# secret-get provides the latest revision on first call, and the same, pinned revision for following calls.

# secrets have an identifying label and consist of key-value pairs.

# Secrets have an application-default lifetime.  But can optionally be set to be scoped to a unit-lifetime or a relation-lifetime

# Access to each secret is granted within a particular relation to either an entire application or to a particular unit.
#     - granting access defaults to any unit on the remote side of the current context if one exists (i.e. in a relation-joined event context)
#       or to an entire application if in that sort of context (i.e. in a relation-joined event context)


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

    def keepitsecretkeepitsafe(self):
        # Load this lazily - we don't want juju to mark our unit as tracking this secret unless the
        # charm actually accesses/uses it.
        return self._retrieve_the_secret()

class MyCharm(CharmBase):
    def __init__(self):

    def _on_install(self, event):

    def _foo_relation_created(self, event):
        if self.is_leader():
            secret = event.add_secret('foo-secret', 'user', 'u0', 'pass', 'p0') # grants entire application access
            event.relation.data[self.app]['foo-secret'] = secret # auto-convert this to the secret uri/id?

    def _foo_relation_joined(self, event):
        secret = event.add_secret('foo-secret', 'user', self.event.unit.name, 'pass', self._genpass(event.unit)) # grants only the joining unit access
        event.relation.data[self.app]['foo-secret'] = secret # auto-convert this to the secret uri/id?

    # sent to secret creator/owner when the secret is due to be updated/rotated.
    def _secret_rotate(self, event):
        self._regen_secret(event.secret, ...)

    # sent to secret creator/owner when secret is expired. Called repeatedly until the secret is removed.
    def _secret_expired(self, event):
        event.secret.remove()
        self._regen_secret(event.secret, ...)

    # sent to creator/owner when all secret consuming/reading units have called secret-get --update,
    # allowing the charm to remove obsolete secret revisions.
    def _secret_remove(self, event):
        event.secret.remove()

    def _regen_secret(self, secret, ...):
        ...
        event.secret.update('user', 'u1', 'pass', 'p0') # calls secret-update

class MyOtherCharm(CharmBase):
    def __init__(self):

    def _foo_relation_changed(self, event):
        secret = self.get_secret(event.relation.data[event.app])
        self._auth(secret)

    def _auth(self, secret):
        password = secret.keepitsafe()
        # ... do special auth

    # sent to all units that have ever read the secret value when the secret gets a new revision (i.e. is updated).
    def _secret_changed(self, event):
        event.secret.update()
        self._auth(event.secret)

