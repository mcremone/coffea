from concurrent.futures import as_completed
import multiprocessing

from tqdm import tqdm

import parsl

from parsl.app.app import python_app

from parsl.providers import LocalProvider
from parsl.channels import LocalChannel
from parsl.config import Config
from parsl.executors import HighThroughputExecutor

from ..executor import futures_handler

from .timeout import timeout

try:
    from collections.abc import Sequence
except ImportError:
    from collections import Sequence

_default_cfg = Config(
    executors=[
        HighThroughputExecutor(
            label="coffea_parsl_default",
            cores_per_worker=1,
            provider=LocalProvider(
                channel=LocalChannel(),
                init_blocks=1,
                max_blocks=1,
            ),
        )
    ],
    strategy=None,
)


def _parsl_initialize(config=None):
    dfk = parsl.load(config)
    return dfk


def _parsl_stop(dfk):
    dfk.cleanup()
    parsl.clear()


@python_app
@timeout
#def derive_chunks(filename, treename, chunksize, ds, timeout=None):
def derive_chunks(filelist, treename, chunksize, timeout=None):
    import uproot
    from collections.abc import Sequence
    from concurrent.futures import ThreadPoolExecutor, TimeoutError

    uproot.XRootDSource.defaults["parallel"] = False
    
    ntot = 0
    files = []
    output = []
    for ds, filename in filelist:
        afile = None
        for i in range(5):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(uproot.open, filename)
                try:
                    afile = future.result(timeout=5)
                except TimeoutError:
                    afile = None
                else:
                    break

        if afile is None:
            raise Exception('unable to open: %s' % filename)
            
        afile = uproot.open(filename)
        tree = None
        if isinstance(treename, str):
            tree = afile[treename]
        elif isinstance(treename, Sequence):
            for name in reversed(treename):
                if name in afile:
                    tree = afile[name]
        else:
            raise Exception('treename must be a str or Sequence but is a %s!' % repr(type(treename)))

        if tree is None:
            raise Exception('No tree found, out of possible tree names: %s' % repr(treename))

        nentries = tree.numentries
        ntot += nentries
        files.append(filename)
        if ntot > chunksize:
            output.append(ds, treename, [(files, chunksize, index) for index in range(nentries // chunksize + 1)])
            files = []
            ntot = 0

    return output


def _parsl_get_chunking(filelist, treename, chunksize, status=True, timeout=None):
    #futures = set(derive_chunks(fn, treename, chunksize, ds, timeout=timeout) for ds, fn in filelist)
    futures = set(derive_chunks(filelist, treename, chunksize, timeout=timeout))

    items = []

    def chunk_accumulator(total, result):
        ds, treename, chunks = result
        for chunk in chunks:
            total.append((ds, chunk[0], treename, chunk[1], chunk[2]))

    futures_handler(futures, items, status, 'files', 'Preprocessing', futures_accumulator=chunk_accumulator)

    return items
