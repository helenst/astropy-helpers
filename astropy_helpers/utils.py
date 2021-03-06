# Licensed under a 3-clause BSD style license - see LICENSE.rst

import contextlib
import imp
import os
import sys

try:
    from importlib import machinery as import_machinery
except ImportError:
    import_machinery = None


# Python 3.3's importlib caches filesystem reads for faster imports in the
# general case. But sometimes it's necessary to manually invalidate those
# caches so that the import system can pick up new generated files.  See
# https://github.com/astropy/astropy/issues/820
if sys.version_info[:2] >= (3, 3):
    from importlib import invalidate_caches
else:
    invalidate_caches = lambda: None


def _get_platlib_dir(cmd):
    """
    Given a build command, return the name of the appropriate platform-specific
    build subdirectory directory (e.g. build/lib.linux-x86_64-2.7)
    """

    plat_specifier = '.{0}-{1}'.format(cmd.plat_name, sys.version[0:3])
    return os.path.join(cmd.build_base, 'lib' + plat_specifier)


def get_numpy_include_path():
    """
    Gets the path to the numpy headers.
    """
    # We need to go through this nonsense in case setuptools
    # downloaded and installed Numpy for us as part of the build or
    # install, since Numpy may still think it's in "setup mode", when
    # in fact we're ready to use it to build astropy now.

    if sys.version_info[0] >= 3:
        import builtins
        if hasattr(builtins, '__NUMPY_SETUP__'):
            del builtins.__NUMPY_SETUP__
        import imp
        import numpy
        imp.reload(numpy)
    else:
        import __builtin__
        if hasattr(__builtin__, '__NUMPY_SETUP__'):
            del __builtin__.__NUMPY_SETUP__
        import numpy
        reload(numpy)

    try:
        numpy_include = numpy.get_include()
    except AttributeError:
        numpy_include = numpy.get_numpy_include()
    return numpy_include


class _DummyFile(object):
    """A noop writeable object."""

    errors = ''  # Required for Python 3.x

    def write(self, s):
        pass

    def flush(self):
        pass


@contextlib.contextmanager
def silence():
    """A context manager that silences sys.stdout and sys.stderr."""

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = _DummyFile()
    sys.stderr = _DummyFile()
    exception_occurred = False
    try:
        yield
    except:
        exception_occurred = True
        # Go ahead and clean up so that exception handling can work normally
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        raise

    if not exception_occurred:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


if sys.platform == 'win32':
    import ctypes

    def _has_hidden_attribute(filepath):
        """
        Returns True if the given filepath has the hidden attribute on
        MS-Windows.  Based on a post here:
        http://stackoverflow.com/questions/284115/cross-platform-hidden-file-detection
        """
        if isinstance(filepath, bytes):
            filepath = filepath.decode(sys.getfilesystemencoding())
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
            assert attrs != -1
            result = bool(attrs & 2)
        except (AttributeError, AssertionError):
            result = False
        return result
else:
    def _has_hidden_attribute(filepath):
        return False


def is_path_hidden(filepath):
    """
    Determines if a given file or directory is hidden.

    Parameters
    ----------
    filepath : str
        The path to a file or directory

    Returns
    -------
    hidden : bool
        Returns `True` if the file is hidden
    """

    name = os.path.basename(os.path.abspath(filepath))
    if isinstance(name, bytes):
        is_dotted = name.startswith(b'.')
    else:
        is_dotted = name.startswith('.')
    return is_dotted or _has_hidden_attribute(filepath)


def walk_skip_hidden(top, onerror=None, followlinks=False):
    """
    A wrapper for `os.walk` that skips hidden files and directories.

    This function does not have the parameter `topdown` from
    `os.walk`: the directories must always be recursed top-down when
    using this function.

    See also
    --------
    os.walk : For a description of the parameters
    """

    for root, dirs, files in os.walk(
            top, topdown=True, onerror=onerror,
            followlinks=followlinks):
        # These lists must be updated in-place so os.walk will skip
        # hidden directories
        dirs[:] = [d for d in dirs if not is_path_hidden(d)]
        files[:] = [f for f in files if not is_path_hidden(f)]
        yield root, dirs, files


def write_if_different(filename, data):
    """Write `data` to `filename`, if the content of the file is different.

    Parameters
    ----------
    filename : str
        The file name to be written to.
    data : bytes
        The data to be written to `filename`.
    """

    assert isinstance(data, bytes)

    if os.path.exists(filename):
        with open(filename, 'rb') as fd:
            original_data = fd.read()
    else:
        original_data = None

    if original_data != data:
        with open(filename, 'wb') as fd:
            fd.write(data)


def import_file(filename, name=None):
    """
    Imports a module from a single file as if it doesn't belong to a
    particular package.

    The returned module will have the optional ``name`` if given, or else
    a name generated from the filename.
    """
    # Specifying a traditional dot-separated fully qualified name here
    # results in a number of "Parent module 'astropy' not found while
    # handling absolute import" warnings.  Using the same name, the
    # namespaces of the modules get merged together.  So, this
    # generates an underscore-separated name which is more likely to
    # be unique, and it doesn't really matter because the name isn't
    # used directly here anyway.
    mode = 'U' if sys.version_info[0] < 3 else 'r'

    if name is None:
        basename = os.path.splitext(filename)[0]
        name = '_'.join(os.path.relpath(basename).split(os.sep)[1:])

    if import_machinery:
        loader = import_machinery.SourceFileLoader(name, filename)
        mod = loader.load_module()
    else:
        with open(filename, mode) as fd:
            mod = imp.load_module(name, fd, filename, ('.py', mode, 1))

    return mod


def resolve_name(name):
    """Resolve a name like ``module.object`` to an object and return it.

    Raise `ImportError` if the module or name is not found.
    """

    parts = name.split('.')
    cursor = len(parts) - 1
    module_name = parts[:cursor]
    attr_name = parts[-1]

    while cursor > 0:
        try:
            ret = __import__('.'.join(module_name), fromlist=[attr_name])
            break
        except ImportError:
            if cursor == 0:
                raise
            cursor -= 1
            module_name = parts[:cursor]
            attr_name = parts[cursor]
            ret = ''

    for part in parts[cursor:]:
        try:
            ret = getattr(ret, part)
        except AttributeError:
            raise ImportError(name)

    return ret


if sys.version_info[0] >= 3:
    def iteritems(dictionary):
        return dictionary.items()
else:
    def iteritems(dictionary):
        return dictionary.iteritems()


def extends_doc(extended_func):
    """
    A function decorator for use when wrapping an existing function but adding
    additional functionality.  This copies the docstring from the original
    function, and appends to it (along with a newline) the docstring of the
    wrapper function.

    Example
    -------

        >>> def foo():
        ...     '''Hello.'''
        ...
        >>> @extends_doc(foo)
        ... def bar():
        ...     '''Goodbye.'''
        ...
        >>> print(bar.__doc__)
        Hello.

        Goodbye.

    """

    def decorator(func):
        func.__doc__ = '\n\n'.join([extended_func.__doc__.rstrip('\n'),
                                    func.__doc__.lstrip('\n')])
        return func

    return decorator
