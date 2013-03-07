#!/usr/bin/python

from versuchung.types import Type, InputParameter, OutputParameter
import logging
import sqlite3
import os, stat


class Database_SQLite(InputParameter, OutputParameter, Type):
    """Can be used as **input parameter** and **output parameter**

    A database backend class for sqlite3 database."""

    # Static cache of all database connections open in system
    # Map from path -> tuple(db_handle, use_count)
    database_connections = {}

    def __init__(self, path = "sqlite3.db"):
        InputParameter.__init__(self)
        OutputParameter.__init__(self)
        Type.__init__(self)

        self.__database_path = path
        self.__database_connection = None

    def inp_setup_cmdline_parser(self, parser):
        self.inp_parser_add(parser, None, self.__database_path)

    def inp_extract_cmdline_parser(self, opts, args):
        self.__database_path = self.inp_parser_extract(opts, None)

    def inp_metadata(self):
        return {self.name: self.__database_path}

    def before_experiment_run(self, parameter_type):
        Type.before_experiment_run(self, parameter_type)
        assert parameter_type in ["input", "output"]
        if parameter_type == "input":
            # Ensure the path does exist
            if not os.path.exists(self.path):
                raise RuntimeError("Database not found: %s" % self.path)
        self.__database_connection = self.__connect(self.path)

        if parameter_type == "output":
            try:
                self.create_table("metadata", [("experiment", "text"), ("metadata", "text")],
                                   primary = "experiment")
                self.execute("INSERT INTO metadata(experiment, metadata) values(?, ?)",
                             self.dynamic_experiment.experiment_identifier,
                             str(self.dynamic_experiment.metadata))
            except sqlite3.OperationalError as e:
                # Metadata table was already generated
                pass


    def after_experiment_run(self, parameter_type):
        Type.before_experiment_run(self, parameter_type)
        assert parameter_type in ["input", "output"]
        self.__database_connection = None
        self.__disconnect(self.path)
        if parameter_type == "output":
            # Remove execute and write permissions for file
            new_mode = os.stat(self.path).st_mode & (stat.S_IROTH | stat.S_IRGRP | stat.S_IRUSR)
            os.chmod(self.path, new_mode)

    @staticmethod
    def __connect(path):
        # Do reference counting on database connections
        if path in Database_SQLite.database_connections:
            (db, count) = Database_SQLite.database_connections[path]
            Database_SQLite.database_connections[path] = (db, count + 1)
            return db
        conn = sqlite3.connect(path)
        Database_SQLite.database_connections[path] = (conn, 1)
        return conn

    @staticmethod
    def __disconnect(path):
        (db, count) = Database_SQLite.database_connections[path]
        db.commit()
        if count == 1:
            db.close()
            del Database_SQLite.database_connections[path]
            return
        Database_SQLite.database_connections[path] = (db, count - 1)

    @property
    def path(self):
        """:return: string -- path to the sqlite database file"""
        return os.path.join(self.base_directory, self.__database_path)

    @property 
    def handle(self):
        """:return: handle -- sqlite3 database handle"""
        assert self.__database_connection
        return self.__database_connection

    def execute(self, command, *args):
        """Execute command including the arguments on the sql
        handle. Question marks in the command are replaces by the ``*args``::

        >>> database.execute("SELECT * FROM metadata WHERE experiment = ?", identifer)
        """
        logging.debug("sqlite: %s %s", str(command), str(args))
        return self.__database_connection.execute(command, args)

    def create_table(self, name, fields = [("key", "text"), ("value", "text")], primary = None):
        """Creates a new table in the database. ``name`` is the name
        of newly created table. The ``fields`` are a list of
        columns. A column is a tuple, its first entry is the name, its
        second entry the column type. If primary is the name of a
        column this column is marked as the primary key for the
        table."""

        CT = "CREATE TABLE " + name + " ("
        for i in range(0, len(fields)):
            field, datatype = fields[i]
            CT += field + " " + datatype
            if field == primary:
                CT += " PRIMARY KEY"
            if i != len(fields) - 1:
                CT += ", "
        CT += ")"
        return self.execute(CT)

    def values(self, table_name, filter_expr = "where experiment = ?", *args):
        """Get the contets of a table in the database. It takes
        addtional to the table name, a filter expression and applies
        all args to the excute command. An example::

           (cols, rows) = database.values("metadata", "")
           for row in rows:
                print cols, rows
        """
        cur = self.handle.cursor()
        cur.execute('select * from ' + table_name + filter_expr,
                    args)

        cols = [x[0] for x in cur.description]
        def generator():
            while True:
                row = cur.fetchone()
                if row == None:
                    cur.close()
                    return
                yield row

        index = cols.index("experiment")
        return cols, generator()


def Database(path = "sqlite3.db", database_type = "sqlite", *args, **kwargs):
    """This is a just a wrapper around the supported database
    abstraction classes. Every other argument and paramater than
    ``database_type`` is forwared directly to those classes.

    Supported database_type abstractions are at the moment:

    - ``sqlite`` -- :class:`~versuchung.database.Database_SQLite`"""
    if database_type == "sqlite":
        return Database_SQLite(path, *args, **kwargs)
    assert False, "Database type %s is not implemented yet" % database_type

class Table(InputParameter, OutputParameter, Type):
    """Can be used as **input parameter** and **output parameter**

    A versuchung table is a table that is aware of experiments. It
    stores for each dataset the experiment it originates from. The
    field list consits either of plain strings, then the column type
    is text. If it's a tuple the first entry is the name and the second its type::

    >>> [("foo", "integer"), "barfoo"]
   
    This will result in two columns, one with type integer and one
    with type text. If a db is given this one is used instead of a
    default sqlite database named ``sqlite3.db``

    The index parameter makes a field the primary key.
    """
    def __init__(self, fields,  index = None, db = None):
        self.read_only = True
        InputParameter.__init__(self)
        OutputParameter.__init__(self)
        Type.__init__(self)

        self.__index = index
        self.__fields = self.__field_typify(["experiment"] + fields)

        if not db:
            self.__db = Database()
        else:
            self.__db = db

    def __field_typify(self, fields):
        real_fields = []
        for f in fields:
            if type(f) in [tuple, list]:
                real_fields.append(tuple(f))
            else:
                # the default field type is text
                assert type(f) == str
                real_fields.append(tuple([f, 'text']))
        return real_fields

    def before_experiment_run(self, parameter_type):
        # Add database object as an 
        self.subobjects["database"] = self.__db
        Type.before_experiment_run(self, parameter_type)

        if parameter_type == "output":
            self.read_only = False
            self.__db.create_table(self.table_name, self.__fields,
                                   primary = self.__index)
    @property
    def database(self):
        """:return: :class:`~versuchung.database.Database` -- the database the table is located in"""
        return self.__db

    @property
    def table_name(self):
        """:return: string -- return the name of the table in the database"""
        assert self.static_experiment
        name = self.name
        try:
            i = self.name.rindex("-")
            name = name[i+1:]
        except:
            pass
        return self.static_experiment.title + "__" + name

    def insert(self, data=None, **kwargs):
        """Insert a dict of data into the database table"""
        assert self.read_only == False
        if data:
            kwargs.update(data)
        kwargs["experiment"] = self.dynamic_experiment.experiment_identifier
        assert set(kwargs.keys()) == set([f for f, t in self.__fields])

        items = kwargs.items()
        insert_statement = "INSERT INTO %s(%s) values(%s)" % (
            self.table_name,
            ", ".join([f for f, t in items]),
            ", ".join(["?" for _ in items]))
        self.__db.execute(insert_statement, *[v for k,v in items])

    def clear(self):
        """Remove all entries associated with the current running experiment"""

        self.__db.execute("DELETE FROM " + self.table_name +" WHERE experiment = ?",
                          self.dynamic_experiment.experiment_identifier)

    @property
    def value(self):
        """The value of the table. It returns a tuple. The first entry
        is a tuple of column headings. The second entry is a list of
        rows, in the same order as the column headings. The column
        that associates the entry with the experiment is stripped
        apart and only data for the static enclosing experiment is
        shown."""
        (cols, rows) = self.__db.values(self.table_name, ' where experiment = ?',
                                        self.static_experiment.experiment_identifier)

        index = cols.index("experiment")
        table = []
        for row in rows:
            l = list(row)
            del l[index]
            table.append(tuple(l))
        del cols[index]

        return tuple(cols), table


class TableDict(Table, dict):
    """Can be used as **input parameter** and **output parameter**

    This uses a :class:`~versuchung.database.Table` as a backend for a
    python dict. This object can be used in the same way
    :class:`~versuchung.tex.PgfKeyDict` is used. Please be aware, that
    the storage and retrieval of keys from the associated table is
    done lazy. Therefore the data is only then visible if the
    experiment was successful.
    """
    def __init__(self, db=None):
        self.__key_name = "key"
        self.__value_name = "value"
        columns = [(self.__key_name, 'text'), (self.__value_name, 'text')]
        Table.__init__(self, columns, index=self.__key_name, db=db)
        dict.__init__(self)

    def insert(self, *args, **kwargs):
        raise NotImplementedError

    def flush(self):
        """Save the current dict content to the database."""
        Table.clear(self)
        for key, value in self.items():
            Table.insert(self,
                         {self.__key_name: key,
                          self.__value_name: value})

    def after_experiment_run(self, parameter_type):
        assert self.parameter_type == parameter_type
        if parameter_type == "output":
            self.flush()
        Table.after_experiment_run(self, parameter_type)

    def before_experiment_run(self, parameter_type):
        Table.before_experiment_run(self, parameter_type)
        if parameter_type == "input":
            (header, values) = self.value
            key_index = header.index(self.__key_name)
            value_index = header.index(self.__value_name)
            self.update([(x[key_index], x[value_index]) for x in values])



class Database_SQlite_Merger:
    def log(self, msg, *args):
        print "merger: " + (msg % args)

    def __init__(self, target_path, source_paths = []):
        self.target_path = target_path
        self.source_paths = {}
        self.target = sqlite3.connect(target_path)

        db_counter = 0
        for source in source_paths:
            assert os.path.exists(source), "Path does not exist " + source
            name = "db_%d" % db_counter
            db_counter += 1
            self.target.execute("ATTACH DATABASE '%s' AS %s" %(source, name))
            self.log("attached %s as %s", source, name)
            self.source_paths[name] = source

    def collect_and_create_tables(self):
        cur = self.target.cursor()
        self.tables = {}
        for db in self.source_paths:
            cur.execute("SELECT * FROM " + db + ".sqlite_master WHERE type = 'table'")
            header = [x[0] for x in cur.description]
            for table in cur.fetchall():
                table = dict(zip(header, table))
                name = table["name"]
                if table["name"] in self.tables:
                    if self.tables[name]["sql"] != table["sql"]:
                        self.log("Two tables with different defintions found: %s" % name)
                        sys.exit(-1)
                    self.tables[name]["databases"].append(db)
                else:
                    self.tables[name] = table
                    self.tables[name]["databases"] = [db]
        for name, table in self.tables.items():
            try:
                cur.execute("DROP TABLE %s" % name)
            except:
                pass
            cur.execute(table["sql"])
            self.log("created table %s", name)

        cur.close()

    def collect_data(self):
        cur = self.target.cursor()

        TableDictrows = set()
        
        for name in self.tables:
            rows = set()
            headers = None
            for db in self.tables[name]["databases"]:
                cur.execute("SELECT * FROM %s.%s" % (db, name))
                for i in cur.fetchall():
                    rows.add(i)
                headers = [x[0] for x in cur.description]

            cur.executemany("INSERT INTO %s (%s) values(%s)" % (\
                    name,
                    ", ".join(headers),
                    ", ".join(["?" for x in headers])
                    ), rows)
            self.log("inserted %d rows into %s", len(rows), name)


            if headers == ["experiment", "key", "value"]:
                TableDictrows.update(rows)
        
        cur.execute("CREATE TABLE IF NOT EXISTS TableDict (experiment text, key text, value text)")
        cur.executemany("INSERT INTO TableDict (experiment, key, value) values(?,?,?)",
                        TableDictrows)
        self.log("inserted %d key-value pairs into TableDict", len(TableDictrows))
        cur.close()
        self.target.commit()

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print sys.argv[0] + " <target-database-file> [<source-db1> <source-db2> ...]"
        print " -- merges different versuchung sqlite databases into a single one"
        sys.exit(-1)

    merger = Database_SQlite_Merger(sys.argv[1], sys.argv[2:])
    merger.collect_and_create_tables()
    merger.collect_data()
