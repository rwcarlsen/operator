
import logging

class Status:
    def __init__(self, kind, msg):
        self.msg = msg
        self.name = kind
    def __str__(self):
        return '<{}:{}>'.format(self.name, self.msg)

class ActiveStatus(Status):
    def __init__(self, msg):
        super().__init__('active', msg)
class BlockedStatus(Status):
    def __init__(self, msg):
        super().__init__('blocked', msg)
class MaintenanceStatus(Status):
    def __init__(self, msg):
        super().__init__('maintenance', msg)
class WaitingStatus(Status):
    def __init__(self, msg):
        super().__init__('waiting', msg)
class UnknownStatus(Status):
    def __init__(self, msg):
        super().__init__('unknown', msg)

class StatusPool:
    _priorities = {'unknown':1, 'active':4, 'blocked': 0, 'waiting': 3, 'maintenance': 2}
    _loglevels = {'unknown': 'warning', 'active': 'debug', 'blocked': 'error', 'waiting':
            'debug', 'maintenance':'debug'}
    def __init__(self, charm, auto_commit=False, logger=None):
        self._statuses = {}
        self._order = {}
        self._charm = charm
        self._logger = logger
        self._next_order = 0
        if auto_commit:
            charm.model.at_hook_exit(self._at_hook_exit)

    def __setitem__(self, key, val):
        if val is None:
            del self._statuses[key]
            return
        if self._logger:
            getattr(self._logger, self._loglevels[val.name])('StatusPool[{!r}]: {}'.format(key, val))

        if key not in self._statuses:
            self._next_order += 1
            self._order[key] = self._next_order

        self._statuses[key] = val

    def _at_hook_exit(self):
        self.commit()

    def commit(self):
        if len(self._statuses) == 0:
            return
        lst = sorted(self._statuses.keys(), key=lambda k: (self._priorities[self._statuses[k].name], self._order[k]))
        self._charm.model.unit.status = self._statuses[lst[0]]

class MockCharm:
    class Model:
        class Unit:
            def __init__(self):
                self.status = UnknownStatus('???')
        def __init__(self):
            self.unit = MockCharm.Model.Unit()
            self._exit_callbacks = []
        def at_hook_exit(self, func):
            self._exit_callbacks.append(func)
    def __init__(self):
        self.model = MockCharm.Model()


def test_foo():
    logger = logging.getLogger(__name__)
    charm = MockCharm()
    status = StatusPool(charm, auto_commit=False, logger=logger)

    status['foo'] = ActiveStatus('foo the foo')
    status['bar'] = BlockedStatus('blocked123')
    status['quuux'] = WaitingStatus('waiting456')
    status['quux'] = WaitingStatus('waiting123')
    status['baz'] = ActiveStatus('foo the baz')

    assert charm.model.unit.status.name == 'unknown'
    status.commit()
    assert charm.model.unit.status.msg == 'blocked123'
    status['bar'] = None
    assert charm.model.unit.status.msg == 'blocked123'
    status.commit()
    assert charm.model.unit.status.msg == 'waiting456'
    status['quuux'] = None
    status.commit()
    assert charm.model.unit.status.msg == 'waiting123'

if __name__ == '__main__':
    test_foo()

