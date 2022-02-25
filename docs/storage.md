
# Accessing Storage from a Charm

(partially inspired by confusion in https://github.com/canonical/operator/issues/646)

When you use storage mounts with juju, they will be automatically mounted into the
charm container at either:

* the specified `location` given in the storage section of metadata.yaml or

* a default location `/var/lib/juju/storage/<storage-name>/<num>` where `num`
  is zero for "normal"/singular storages or integer id for storages that
  support `multiple` attachments.

The operator framework provides the `Model.storages` dict-like member
that maps storage names to a list of storages mounted under that name.  It is
a list in order to handle the case of `multipl`y configured storage.  For the
basic singular case, you will simply access the first/only element of this
list.

Charm developers should *not* directly assume a location/path for mounted
storage.  To access mounted storage resources, retrieve the desired
storage's mount location from within your charm code - e.g.:

```python
def _my_hook_function(self, event):
    ...
    storage = self.model.storages['my-storage'][0]
    root = storage.location

    fname = 'foo.txt'
    fpath = os.path.join(root, fname)
    with open(fpath, 'w') as f:
        f.write('super important config info')
    ...
```

# Understanding Storage Events/Lifecycle

(This section was inspired by https://discourse.charmhub.io/t/writing-charms-that-use-storage/1128/4)

While juju provides an `add-storage` command, this does not "grow" existing storage
instances/mounts like you might expect.  Rather it works by increasing the
number of storage instances available/mounted for storages that are configured
with the `multiple` parameter - e.g.:

```yaml
storage:
    my-storage:
        type: filesystem
        multiple:
            range: 1-10
```

Juju will generally deploy applications with the minimum of the range - or 1 storage
instance in this case.  Storage with this type of `multiple:...` configuration
will have each instance residing under an indexed subdirectory of that
storage's main directory - e.g.  `/var/lib/juju/storage/my-storage/1`, etc.
etc.  Running `juju add-storage <unit> my-storage=32G,2` will add two
additional instances to this storage - e.g.: `/var/lib/juju/storage/my-storage/2` and
`/var/lib/juju/storage/my-storage/3`.  "Adding" storage does not modify or
affect existing storage mounts.

# Testing a Charm's Use of Storage
