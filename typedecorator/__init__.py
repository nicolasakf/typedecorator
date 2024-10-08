#!/usr/bin/env python
# Copyright (C) 2014. Senko Rasic <senko.rasic@goodcode.io>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
A decorator-based implementation of type checks.

Provides @params, @returns and @void decorators for annotating function
parameters, return value and the non-existence of return value, respectively.

Both @params and @returns take type signatures that can describe both simple
and complex types.

A type signature can be:

1. A type, such as `int`, `str`, `bool`, `object`, `dict`, `list`, or a
custom class, requiring that the value be of specified type or a subclass of
the specified type. Since every type is a subclass of `object`, `object`
matches any type.

2. A list containing a single element, requiring that the value be a list of
values, all matching the type signature of that element. For example, a type
signature specifying a list of integers would be `[int]`.

3. A tuple containing one or more elements, requiring that the value be a tuple
whose elements match the type signatures of each element of the tuple. For
eample, type signature `(int, str, bool)` matches tuples whose first element
is an integer, second a string and third a boolean value.

4. A dictionary containing a single element, requiring that the value be a
dictionary with keys of type matching the dict key, and values of type
matching the dict value. For example, `{str:object}` describes a dictionary
with string keys, and anything as values.

5. A set containing a single element, requiring that the value be a set
with elements of type matching the set element. For example, `{str}` matches
any set consisting solely of strings.

6. `xrange` (or `range` in Python 3), matching any iterator.

7. An instance of `typedecorator.Union`, requiring that the value be of any of
the types listed when creating the `Union` instance. For example,
`Union(int, str, type(None))` matches integers, strings and `None`.

8. An instance of `typedecorator.Nullable`, requiring that the value is either
of the type specified when creating the `Nullable` instance, or None. For
example, `Nullable(str)` matches strings and `None`.

These rules are recursive, so it is possible to construct arbitrarily
complex type signatures. Here are a few examples:

* `{str: (int, [MyClass])}` - dictionary with string keys, where values are
    tuples with first element being an integer, and a second being a list
    of instances of MyClass

* `{str: types.FunctionType}` - dictionary mapping strings to functions

* `{xrange}` - set of iterators

Note that `[object]` is the same as `list`, `{object:object}` is the same
as `dict` and `{object}` is the same as  `set`.

"""

import inspect
import logging
import traceback

__version__ = '0.0.6'

__all__ = ['returns', 'void', 'params', 'Union', 'Nullable', 'Enum', 'typed', 'NoneType']

try:
    from mock import Mock
except:
    Mock = None

try:
    range_type = xrange
except NameError:
    range_type = range

try:
    string_type = basestring
except NameError:
    string_type = str

_logger = logging.getLogger(__name__)
_loglevel = None  # logging.LOGLEVEL to use
_exception = TypeError  # exception to throw on type error (eg. TypeError)


def _type_error(msg, stack=None):
    if _loglevel:
        if not stack:
            stack = traceback.extract_stack()[-4]
        path, line, in_func, instr = stack
        if instr:
            instr = ': ' + instr
        log_msg = 'File "%s", line %d, in %s: %s%s' % (
            path, line, in_func, msg, instr)

        _logger.log(_loglevel, log_msg)

    if _exception:
        raise _exception(msg)


class Union(object):
    __slots__ = ('types',)

    def __init__(self, *types):
        self.types = types

    def __iter__(self):
        return iter(self.types)


def Nullable(t):
    return Union(t, type(None))


def _constraint_to_string(t):
    if isinstance(t, type):
        return t.__name__
    if isinstance(t, string_type):
        return t
    elif isinstance(t, list) and len(t) == 1:
        return '[%s]' % _constraint_to_string(t[0])
    elif isinstance(t, tuple):
        return '(%s)' % ', '.join(_constraint_to_string(x) for x in t)
    elif isinstance(t, dict) and len(t) == 1:
        k, v = list(t.items())[0]
        return '{%s:%s}' % (_constraint_to_string(k), _constraint_to_string(v))
    elif isinstance(t, set) and len(t) == 1:
        return '{%s}' % _constraint_to_string(list(t)[0])
    elif isinstance(t, Union):
        return 'U(%s)' % (', '.join(_constraint_to_string(x) for x in t))
    elif isinstance(t, Enum):
        return 'Enum[%s]' % (', '.join(_constraint_to_string(x) for x in t))
    else:
        raise TypeError('Invalid type signature')


def _check_constraint_validity(t):
    if isinstance(t, type):
        return True
    elif isinstance(t, string_type):
        return True
    elif isinstance(t, list) and len(t) == 1:
        return _check_constraint_validity(t[0])
    elif isinstance(t, tuple):
        return all(_check_constraint_validity(x) for x in t)
    elif isinstance(t, dict) and len(t) == 1:
        k, v = list(t.items())[0]
        return _check_constraint_validity(k) and _check_constraint_validity(v)
    elif isinstance(t, set) and len(t) == 1:
        return _check_constraint_validity(list(t)[0])
    elif isinstance(t, Union):
        return all(_check_constraint_validity(x) for x in t)
    elif isinstance(t, Enum):
        return all(_check_constraint_validity(x) for x in t)
    else:
        raise TypeError('Invalid type signature')


def class_tree(obj):
    """Return list of names of the object's class and all its parent classes.

    For new-style classes, this duplicates one name, but that doesn't cause
    problems.
    """
    return [obj.__class__.__name__] + [base.__name__ for base in type(obj).mro()]


def _verify_type_constraint(v, t):
    if Mock and isinstance(v, Mock):
        return True
    if isinstance(t, Enum):
        return v in t
    elif t is range_type and hasattr(v, '__iter__') and callable(v.__iter__):
        return True
    elif isinstance(t, type):
        return isinstance(v, t)
    elif isinstance(t, string_type) and t in class_tree(v):
        return True
    elif isinstance(t, list) and isinstance(v, list):
        return all(_verify_type_constraint(vx, t[0]) for vx in v)
    elif isinstance(t, tuple) and isinstance(v, tuple) and len(t) == len(v):
        return all(_verify_type_constraint(vx, tx) for vx, tx in zip(v, t))
    elif isinstance(t, dict) and isinstance(v, dict):
        tk, tv = list(t.items())[0]
        return all(_verify_type_constraint(vk, tk) and
                   _verify_type_constraint(vv, tv) for vk, vv in v.items())
    elif isinstance(t, set) and isinstance(v, set):
        tx = list(t)[0]
        return all(_verify_type_constraint(vx, tx) for vx in v)
    elif isinstance(t, Union):
        return any(_verify_type_constraint(v, tx) for tx in t)
    else:
        return False


def returns(return_type):
    """
    Assert that function returns value of specific type

    Example:

        @returns(int)
        def get_random_number():
            return 4  # http://xckd.com/221/

    See module documentation for more information about type signatures.

    """
    _check_constraint_validity(return_type)

    def deco(fn):
        if not hasattr(fn, '__def_site__'):
            if hasattr(fn, '__code__'):
                fc = fn.__code__
            else:
                fc = fn.func_code
            fn.__def_site__ = (fc.co_filename, fc.co_firstlineno, fn.__name__, '')

        def wrapper(*args, **kwargs):
            retval = fn(*args, **kwargs)
            if not _verify_type_constraint(retval, return_type):
                if retval is None and return_type is not type(None):
                    _type_error("non-void function didn't return a value", stack=fn.__def_site__)
                elif retval is not None and return_type is type(None):
                    _type_error("void function returned a value", stack=fn.__def_site__)
                else:
                    _type_error("function returned value %s not matching "
                                "signature %s" % (repr(retval), _constraint_to_string(return_type)),
                                stack=fn.__def_site__)
            return retval

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = fn.__module__
        wrapper.__return_type__ = return_type
        return wrapper

    return deco


void = returns(type(None))
void.__doc__ = """Annotate function returning nothing"""


def params(**types):
    """
    Assert that function is called with arguments of correct types

    Example:

        @params(a=int)
        def double(a):
            return a * 2

    See module documentation for more information about type signatures.

    Note: this decorator must be used directly on the function being annotated
    (ie. there should be no other decorators "between" this one and the
    function), because it inspects the function argument declarations.

    This means that, if using both @returns and @params, @returns must go
    first, as in this example:

        @returns(int)
        @params(a=int, b=int)
        def add(a, b):
            return a + b

    """

    for arg_name, arg_type in types.items():
        _check_constraint_validity(arg_type)

    def deco(fn):
        if hasattr(fn, '__return_type__'):
            raise TypeError('You must use @returns before @params')

        if hasattr(fn, '__code__'):
            fc = fn.__code__
        else:
            fc = fn.func_code

        if not hasattr(fn, '__def_site__'):
            fn.__def_site__ = (fc.co_filename, fc.co_firstlineno, fn.__name__, '')
        if hasattr(inspect, 'getfullargspec'):
            arg_names, va_args, va_kwargs, _, _, _, _ = inspect.getfullargspec(fn)
        else:
            arg_names, va_args, va_kwargs, _ = inspect.getargspec(fn)

        for arg in ['self', 'cls']:
            if (arg in arg_names) and (arg not in types):
                types[arg] = object
        if any(arg not in arg_names for arg in types.keys()) or any(arg not in types for arg in arg_names):
            raise TypeError("Annotation doesn't match function signature")

        def wrapper(*args, **kwargs):
            for arg, name in zip(args, arg_names):
                if not _verify_type_constraint(arg, types[name]):
                    _type_error("argument %s = %s doesn't match "
                                "signature %s" % (name, repr(arg),
                                                  _constraint_to_string(types[name])))

            for k, v in kwargs.items():
                if k not in types:
                    if not va_kwargs:
                        _type_error("unknown keyword argument %s "
                                    "(positional specified as keyword?)" % k)
                elif not _verify_type_constraint(v, types[k]):
                    _type_error("keyword argument %s = %s "
                                "doesn't match signature %s" % (k, repr(v),
                                                                _constraint_to_string(types[k])))
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = fn.__module__
        return wrapper

    return deco


def typed(fn):
    """Interpret Python3 function annotations as type signatures.

    This decorator enables use of Python3 syntactic sugar for specifying
    type signatures in a more readable way than using decorators.

    Argument annotations are treated as arguments to @params. Return value
    annotation is treated as argument to @returns. Either are optional, but
    at least one should be given if this decorator is used.
    """

    if not hasattr(fn, '__annotations__'):
        raise TypeError("Function not annotated with Python3 annotations")

    return_type = fn.__annotations__.get('return')
    param_types = fn.__annotations__.copy()

    if return_type:
        del param_types['return']

    if param_types:
        fn = params(**param_types)(fn)

    if return_type:
        fn = returns(return_type)(fn)

    fn.__annotations__ = {}
    return fn


class Enum(object):
    __slots__ = ('enums',)

    def __init__(self, *enums):
        self.enums = enums

    def __iter__(self):
        return iter(self.enums)


NoneType = type(None)
