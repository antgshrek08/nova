# Roll back a self-update whose previous launch never became healthy, before
# any of the updated modules are imported. See source_updates.recover_on_boot.
from . import source_updates as _source_updates

_source_updates.recover_on_boot()
