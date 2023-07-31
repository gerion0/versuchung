#!/usr/bin/python

from __future__ import print_function

from versuchung.experiment import Experiment
from versuchung.archives import TarArchive

class TarArchiveText(Experiment):
    inputs = {"tar": TarArchive("test.tar.gz")}

    def run(self):
        with self.tmp_directory as path:
            directory = self.i.tar.value
        assert len(directory.value) == 2
        assert "ABC" in directory.value
        assert "Hallo" in directory.value
        print("success")


if __name__ == "__main__":
    import sys
    import shutil
    t = TarArchiveText()
    dirname = t()
    shutil.rmtree(dirname)
