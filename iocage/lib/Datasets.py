# Copyright (c) 2014-2017, iocage
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
import typing
import libzfs

import iocage.lib.errors
import iocage.lib.helpers

# MyPy
import iocage.lib.Types


class Datasets:

    ZFS_POOL_ACTIVE_PROPERTY: str = "org.freebsd.ioc:active"

    root: libzfs.ZFSDataset
    zfs: 'iocage.lib.ZFS.ZFS'
    logger: 'iocage.lib.Logger.Logger'
    _datasets: typing.Dict[str, libzfs.ZFSDataset] = {}

    def __init__(
        self,
        root: typing.Optional[libzfs.ZFSDataset]=None,
        pool: typing.Optional[libzfs.ZFSPool]=None,
        zfs: 'iocage.lib.ZFS.ZFS'=None,
        logger: 'iocage.lib.Logger.Logger'=None
    ) -> None:

        self.logger = iocage.lib.helpers.init_logger(self, logger)
        self.zfs = iocage.lib.helpers.init_zfs(self, zfs)

        if isinstance(root, libzfs.ZFSDataset):
            self.root = root
            return

        if (pool is not None) and isinstance(pool, libzfs.ZFSPool):
            self.root = self._get_or_create_dataset(
                "iocage",
                root_name=pool.name,
                pool=pool
            )
            return

        active_pool = self.active_pool

        if active_pool is None:
            raise iocage.lib.errors.IocageNotActivated(logger=self.logger)
        else:
            self.root = self.zfs.get_dataset(f"{active_pool.name}/iocage")

    @property
    def active_pool(self) -> typing.Optional[libzfs.ZFSPool]:
        for pool in self.zfs.pools:
            if self._is_pool_active(pool):
                return pool
        return None

    @property
    def releases(self) -> libzfs.ZFSDataset:
        return self._get_or_create_dataset("releases")

    @property
    def base(self) -> libzfs.ZFSDataset:
        return self._get_or_create_dataset("base")

    @property
    def jails(self) -> libzfs.ZFSDataset:
        return self._get_or_create_dataset("jails")

    @property
    def logs(self) -> libzfs.ZFSDataset:
        return self._get_or_create_dataset("log")

    def activate(
        self,
        mountpoint=None
    ) -> None:

        self.activate_pool(self.root.pool, mountpoint)

    def activate_pool(
        self,
        pool: libzfs.ZFSPool,
        mountpoint: typing.Optional[iocage.lib.Types.AbsolutePath]=None
    ) -> None:

        if self._is_pool_active(pool):
            msg = f"ZFS pool '{pool.name}' is already active"
            self.logger.warn(msg)

        if not isinstance(pool, libzfs.ZFSPool):
            raise iocage.lib.errors.ZFSPoolInvalid("cannot activate")

        if pool.status == "UNAVAIL":
            raise iocage.lib.errors.ZFSPoolUnavailable(pool.name)

        other_pools = filter(lambda x: x.name != pool.name, self.zfs.pools)
        for other_pool in other_pools:
            self._deactivate_pool(other_pool)

        self._activate_pool(pool)

        if mountpoint is not None:
            self.root = self._get_or_create_dataset(
                "iocage",
                pool=pool,
                mountpoint=mountpoint
            )
        else:
            self.root = self._get_or_create_dataset(
                "iocage",
                pool=pool
            )

    def _is_pool_active(self, pool: libzfs.ZFSPool) -> bool:
        return iocage.lib.helpers.parse_user_input(self._get_pool_property(
            pool,
            self.ZFS_POOL_ACTIVE_PROPERTY
        ))

    def _get_pool_property(
        self,
        pool: libzfs.ZFSPool,
        prop: str
    ) -> str:

        return pool.root_dataset.properties[prop].value

    def _get_dataset_property(
        self,
        dataset: libzfs.ZFSDataset,
        prop: str
    ) -> typing.Optional[str]:

        try:
            return dataset.properties[prop].value
        except:
            return None

    def _activate_pool(self, pool: libzfs.ZFSPool) -> None:
        self._set_pool_activation(pool, True)

    def _deactivate_pool(self, pool: libzfs.ZFSPool) -> None:
        self._set_pool_activation(pool, False)

    def _set_pool_activation(self, pool: libzfs.ZFSPool, state: bool) -> None:
        value = "yes" if state is True else "no"
        self._set_zfs_property(
            pool.root_dataset,
            self.ZFS_POOL_ACTIVE_PROPERTY,
            value
        )

    def _set_zfs_property(
        self,
        dataset: libzfs.ZFSDataset,
        name: str,
        value: str
    ) -> None:

        current_value = self._get_dataset_property(dataset, name)
        if current_value != value:
            self.logger.verbose(
                f"Set ZFS property {name}='{value}'"
                f" on dataset '{dataset.name}'"
            )
            dataset.properties[name] = libzfs.ZFSUserProperty(value)

    def _get_or_create_dataset(
        self,
        name: str,
        root_name: str=None,
        pool: typing.Optional[libzfs.ZFSPool]=None,
        mountpoint: typing.Optional[iocage.lib.Types.AbsolutePath]=None
    ) -> libzfs.ZFSDataset:

        if not iocage.lib.helpers.validate_name(name):
            raise NameError(f"Invalid 'name' for Dataset: {name}")

        try:
            return self._datasets[name]
        except (AttributeError, KeyError):
            pass

        if root_name is not None:
            root_dataset_name = root_name
        else:
            root_dataset_name = self.root.name

        target_pool: libzfs.ZFSPool
        if pool is not None:
            target_pool = pool
        else:
            target_pool = self.root.pool

        dataset_name = f"{root_dataset_name}/{name}"
        try:
            dataset = self.zfs.get_dataset(dataset_name)
        except:
            target_pool.create(dataset_name, {})
            dataset = self.zfs.get_dataset(dataset_name)

            if mountpoint is not None:
                mountpoint_property = libzfs.ZFSUserProperty(mountpoint)
                dataset.properties["mountpoint"] = mountpoint_property

            dataset.mount()
        self._datasets[dataset_name] = dataset

        return dataset
