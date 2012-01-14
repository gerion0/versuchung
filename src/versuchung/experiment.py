#!/usr/bin/python

from optparse import OptionParser
import datetime
import logging
import pprint
from versuchung.types import InputParameter, OutputParameter, Type, Directory
from versuchung.tools import JavascriptStyleDictAccess, setup_logging
import sys, os
import hashlib
import shutil
import copy
import tempfile

class ExperimentError(Exception):
    pass

class Experiment(Type, InputParameter):
    """Can be used as: **input parameter**"""

    version = 1
    """Version of the experiment, defaults to 1. The version is
    included in the metadata **and** used for the metadata hash."""


    i = None
    """Shorthand for :attr:`~.inputs`"""

    inputs = {}
    """In the input dictionary all input parameters are defined. They
    may and will influence the metadata and the metadata hash. Only
    objects which are marked as **input parameters** may be used
    here. The key in this ``dict`` is used as :attr:`~.name` attribute
    and propagated to the parameters. From these input parameters the
    command line interface is created.

    This ``dict`` can not only be used as a dictionary but also a
    object with the dot-notation (this behaviour is known and widely
    used in javascript). And there is i as a shorthand.

    >>> self.inputs["string_parameter"]
    <versuchung.types.String object at 0xb73fabec>
    >>> self.inputs.string_parameter
    <versuchung.types.String object at 0xb73fabec>
    >>> self.i.string_parameter
    <versuchung.types.String object at 0xb73fabec>
    """

    o = None
    """Shorthand for :attr:`~.outputs`"""

    outputs = {}
    """Similar to the :attr:`~.inputs` attribute, in the output
    dictionary all experiment results are defined. Only objects that
    are explicitly marked as **output parameters** can be used
    here.

    When a experiment is used as an input parameter. The results of
    the old experiment can be accessed through this attribute. Of
    course at all points the short hands for inputs and outputs can be
    used. As well as the javascript style access to dictionary members.

    >>> self.inputs["experiment"].outputs["out_file"]
    <versuchung.types.File object at 0xb736220c>
    >>> self.i.experiment.o.out_file
    <versuchung.types.File object at 0xb736220c>
    """

    title = None
    """Title of the experiment, this is normally the classname"""

    name = None
    """The name of the object. This is in execution mode (Experiment
    instance is the executed experiment) the result set name
    (str). When the experiment is used as input parameter it is the
    key-value in the :attr:`~.inputs` dictionary."""

    def __init__(self, default_experiment_instance = None):
        """The constructor of an experiment just filles in the
        necessary attributes but has *no* sideeffects on the outside
        world.

        :param default_experiment_instance: If used as input
              parameter, this is the default result set used. For
              example
              ``"SimpleExperiment-aeb298601cdc582b1b0d8260195f6cfd"``
        :type default_experiment_instance: str.

        """

        self.title = self.__class__.__name__
        self.name  = default_experiment_instance

        self.__experiment_instance = default_experiment_instance
        # Copy input and output objects
        self.inputs = JavascriptStyleDictAccess(copy.deepcopy(self.__class__.inputs))
        self.i = self.inputs
        self.outputs = JavascriptStyleDictAccess(copy.deepcopy(self.__class__.outputs))
        self.o = self.outputs

        for (name, inp) in self.inputs.items():
            if not isinstance(inp, InputParameter):
                print "%s cannot be used as an input parameter" % name
                sys.exit(-1)
            inp.name = name

        for (name, outp) in self.outputs.items():
            if not isinstance(outp, OutputParameter):
                print "%s cannot be used as an output parameter" % name
                sys.exit(-1)
            outp.name = name




    def __setup_parser(self):
        self.__parser = OptionParser("%prog <options>")
        self.__parser.add_option('-d', '--base-dir', dest='base_dir', action='store',
                                 help="Directory which is used for storing the experiment data",
                                 default = ".")
        self.__parser.add_option('-l', '--list', dest='do_list', action='store_true',
                                 help="list all experiment results")
        self.__parser.add_option('-v', '--verbose', dest='verbose', action='count',
                                 help="increase verbosity (specify multiple times for more)")

        for (name, inp) in self.inputs.items():
            inp.inp_setup_cmdline_parser(self.__parser)

    def __setup_tmp_directory(self):
        """Creat temporary directory and assign it to every input and
        output directories tmp_directory slots"""
        # Create temp directory
        self.tmp_directory = Directory(tempfile.mkdtemp())
        self.tmp_directory.base_directory = self.pwd

        for (name, inp) in self.inputs.items():
            if hasattr(inp, 'tmp_directory'):
                inp.tmp_directory = self.tmp_directory
        for (name, outp) in self.outputs.items():
            if hasattr(outp, 'tmp_directory'):
                outp.tmp_directory = self.tmp_directory

    def execute(self, args = [], **kwargs):
        """Calling this method will be executed.

        :param args: The command line arguments, normally ``sys.argv``
        :type args: list.

        :kwargs: The keyword arguments can be used to overwrite the
          default values of the experiment, without assembling a command
          line.

        The normal mode of operation is to give ``sys.argv`` as
        argument:

        >>> experiment.execute(sys.argv)

        But with keyword arguments the following two expression result
        in the same result set:

        >>> experiment.execute(["--input_parameter", "foo"])
        >>> experiment.execute(input_parameter="foo")
        """
        self.__setup_parser()
        (opts, args) = self.__parser.parse_args(args)
        os.chdir(opts.base_dir)
        self.pwd = os.path.abspath(os.curdir)
        setup_logging(opts.verbose)


        if opts.do_list:
            for experiment in os.listdir(self.pwd):
                if experiment.startswith(self.title):
                    self.__do_list(self.__class__(experiment))
            return None

        for key in kwargs:
            if not hasattr(opts, key):
                raise AttributeError("No argument called %s" % key)
            setattr(opts, key, kwargs[key])

        self.__setup_tmp_directory()


        for (name, inp) in self.inputs.items():
            inp.base_directory = self.pwd
            ret = inp.inp_extract_cmdline_parser(opts, args)
            if ret:
                (opts, args) = ret

        self.__experiment_instance = self.__setup_output_directory()
        self.name = self.__experiment_instance
        self.__output_directory = os.path.join(self.pwd, self.__experiment_instance)

        for (name, outp) in self.outputs.items():
            outp.base_directory = self.__output_directory
            outp.outp_setup_output()

        self.run()

        for (name, outp) in self.outputs.items():
            outp.outp_tear_down_output()

        shutil.rmtree(self.tmp_directory.path)

        return self.__experiment_instance

    __call__ = execute
    """A experiment can also executed by calling it, :attr:`execute` will be called.

    >>> experiment(sys.argv)"""


    def __do_list(self, experiment, indent = 0):
        with open(os.path.join(experiment.__experiment_instance, "metadata")) as fd:
            content = fd.read()
        d = eval(content)
        content = experiment.__experiment_instance + "\n" + content
        print "+%s%s" % ("-" * indent,
                        content.strip().replace("\n", "\n|" + (" " * (indent+1))))
        for dirname in os.listdir("."):
            if dirname in d.values():
                self.__do_list(Experiment(dirname), indent + 3)

    def __setup_output_directory(self):
        metadata = {}
        for name in self.inputs:
            metadata.update( self.inputs[name].inp_metadata() )
        m = hashlib.md5()
        m.update("version %d" % self.version)
        for key in sorted(metadata.keys()):
            m.update(key + " " + metadata[key])

        self.__experiment_instance = "%s-%s" %(self.title, m.hexdigest())
        output_path = os.path.join(self.pwd, self.__experiment_instance)
        if os.path.exists(output_path):
            logging.info("Output directory existed already, purging it")
            shutil.rmtree(output_path)

        os.mkdir(output_path)

        # Here the hash is already calculated, so we can change the
        # metadata nonconsitent
        metadata["date"] = str(datetime.datetime.now())
        metadata["experiment-name"] = self.title
        metadata["experiment-version"] = self.version

        fd = open(os.path.join(output_path, "metadata"), "w+")
        fd.write(pprint.pformat(metadata) + "\n")
        fd.close()

        return self.__experiment_instance

    ### Input Type
    def inp_setup_cmdline_parser(self, parser):
        self.inp_parser_add(parser, None, self.__experiment_instance)

    def inp_extract_cmdline_parser(self, opts, args):
        self.__experiment_instance = self.inp_parser_extract(opts, None)
        self.name = self.__experiment_instance
        if not self.__experiment_instance:
            print "Missing argument for %s" % self.title
            raise ExperimentError
        for (name, outp) in self.outputs.items():
            outp.base_directory = os.path.join(self.base_directory, self.__experiment_instance)
    def inp_metadata(self):
        return {self.title: self.__experiment_instance}

    def run(self):
        """This method is the hearth of every experiment and must be
        implemented by the user. It is called when the experiment is
        executed. Before all input parameters are parsed, the output
        directory is set up. Afterwards all temporary data is removed
        and the output parameters are deinitialized."""
        raise NotImplemented