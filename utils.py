# Python MPV library module
# Copyright (C) 2017 Sebastian Götte <code@jaseg.net>
from win32gui import FindWindow, SendMessage, FindWindowEx, EnumWindows, GetForegroundWindow, ShowWindow
from win32api import GetAsyncKeyState
from functools import partial, wraps
from warnings import warn
from sys import stdout
from time import sleep
from ctypes import *
from os import path
import ctypes.util
import collections
import threading
import traceback
import sys
import re

backend = CDLL(path.join(getcwd(),'mpv-1.dll'))
fs_enc = 'utf-8'

class MpvHandle(c_void_p):
    pass

class MpvRenderCtxHandle(c_void_p):
    pass

class MpvOpenGLCbContext(c_void_p):
    pass

class PropertyUnavailableError(AttributeError):
    pass

class ErrorCode(object):
    SUCCESS                 = 0
    EVENT_QUEUE_FULL        = -1
    NOMEM                   = -2
    UNINITIALIZED           = -3
    INVALID_PARAMETER       = -4
    OPTION_NOT_FOUND        = -5
    OPTION_FORMAT           = -6
    OPTION_ERROR            = -7
    PROPERTY_NOT_FOUND      = -8
    PROPERTY_FORMAT         = -9
    PROPERTY_UNAVAILABLE    = -10
    PROPERTY_ERROR          = -11
    COMMAND                 = -12
    LOADING_FAILED          = -13
    AO_INIT_FAILED          = -14
    VO_INIT_FAILED          = -15
    NOTHING_TO_PLAY         = -16
    UNKNOWN_FORMAT          = -17
    UNSUPPORTED             = -18
    NOT_IMPLEMENTED         = -19
    GENERIC                 = -20

    EXCEPTION_DICT = {
             0:     None,
            -1:     lambda *a: MemoryError('mpv event queue full', *a),
            -2:     lambda *a: MemoryError('mpv cannot allocate memory', *a),
            -3:     lambda *a: ValueError('Uninitialized mpv handle used', *a),
            -4:     lambda *a: ValueError('Invalid value for mpv parameter', *a),
            -5:     lambda *a: AttributeError('mpv option does not exist', *a),
            -6:     lambda *a: TypeError('Tried to set mpv option using wrong format', *a),
            -7:     lambda *a: ValueError('Invalid value for mpv option', *a),
            -8:     lambda *a: AttributeError('mpv property does not exist', *a),
            -9:     lambda *a: TypeError('Tried to get/set mpv property using wrong format, or passed invalid value', *a),
            -10:    lambda *a: PropertyUnavailableError('mpv property is not available', *a),
            -11:    lambda *a: RuntimeError('Generic error getting or setting mpv property', *a),
            -12:    lambda *a: SystemError('Error running mpv command', *a),
            -14:    lambda *a: RuntimeError('Initializing the audio output failed', *a),
            -15:    lambda *a: RuntimeError('Initializing the video output failed'),
            -16:    lambda *a: RuntimeError('There was no audio or video data to play. This also happens if the file '
                                            'was recognized, but did not contain any audio or video streams, or no '
                                            'streams were selected.'),
            -17:    lambda *a: RuntimeError('When trying to load the file, the file format could not be determined, '
                                            'or the file was too broken to open it'),
            -18:    lambda *a: ValueError('Generic error for signaling that certain system requirements are not fulfilled'),
            -19:    lambda *a: NotImplementedError('The API function which was called is a stub only'),
            -20:    lambda *a: RuntimeError('Unspecified error') }

    @staticmethod
    def default_error_handler(ec, *args):
        return ValueError(_mpv_error_string(ec).decode('utf-8'), ec, *args)

    @classmethod
    def raise_for_ec(kls, ec, func, *args):
        ec = 0 if ec > 0 else ec
        ex = kls.EXCEPTION_DICT.get(ec , kls.default_error_handler)
        if ex:
            raise ex(ec, *args)


class MpvFormat(c_int):
    NONE        = 0
    STRING      = 1
    OSD_STRING  = 2
    FLAG        = 3
    INT64       = 4
    DOUBLE      = 5
    NODE        = 6
    NODE_ARRAY  = 7
    NODE_MAP    = 8
    BYTE_ARRAY  = 9

    def __eq__(self, other):
        return self is other or self.value == other or self.value == int(other)

    def __repr__(self):
        return ['NONE', 'STRING', 'OSD_STRING', 'FLAG', 'INT64', 'DOUBLE', 'NODE', 'NODE_ARRAY', 'NODE_MAP',
                'BYTE_ARRAY'][self.value]

    def __hash__(self):
        return self.value


class MpvEventID(c_int):
    NONE                    = 0
    SHUTDOWN                = 1
    LOG_MESSAGE             = 2
    GET_PROPERTY_REPLY      = 3
    SET_PROPERTY_REPLY      = 4
    COMMAND_REPLY           = 5
    START_FILE              = 6
    END_FILE                = 7
    FILE_LOADED             = 8
    TRACKS_CHANGED          = 9
    TRACK_SWITCHED          = 10
    IDLE                    = 11
    PAUSE                   = 12
    UNPAUSE                 = 13
    TICK                    = 14
    SCRIPT_INPUT_DISPATCH   = 15
    CLIENT_MESSAGE          = 16
    VIDEO_RECONFIG          = 17
    AUDIO_RECONFIG          = 18
    METADATA_UPDATE         = 19
    SEEK                    = 20
    PLAYBACK_RESTART        = 21
    PROPERTY_CHANGE         = 22
    CHAPTER_CHANGE          = 23

    ANY = ( SHUTDOWN, LOG_MESSAGE, GET_PROPERTY_REPLY, SET_PROPERTY_REPLY, COMMAND_REPLY, START_FILE, END_FILE,
            FILE_LOADED, TRACKS_CHANGED, TRACK_SWITCHED, IDLE, PAUSE, UNPAUSE, TICK, SCRIPT_INPUT_DISPATCH,
            CLIENT_MESSAGE, VIDEO_RECONFIG, AUDIO_RECONFIG, METADATA_UPDATE, SEEK, PLAYBACK_RESTART, PROPERTY_CHANGE,
            CHAPTER_CHANGE )

    def __repr__(self):
        return ['NONE', 'SHUTDOWN', 'LOG_MESSAGE', 'GET_PROPERTY_REPLY', 'SET_PROPERTY_REPLY', 'COMMAND_REPLY',
                'START_FILE', 'END_FILE', 'FILE_LOADED', 'TRACKS_CHANGED', 'TRACK_SWITCHED', 'IDLE', 'PAUSE', 'UNPAUSE',
                'TICK', 'SCRIPT_INPUT_DISPATCH', 'CLIENT_MESSAGE', 'VIDEO_RECONFIG', 'AUDIO_RECONFIG',
                'METADATA_UPDATE', 'SEEK', 'PLAYBACK_RESTART', 'PROPERTY_CHANGE', 'CHAPTER_CHANGE'][self.value]

    @classmethod
    def from_str(kls, s):
        return getattr(kls, s.upper().replace('-', '_'))


identity_decoder = lambda b: b
strict_decoder = lambda b: b.decode('utf-8')
def lazy_decoder(b):
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b

class MpvNodeList(Structure):
    def array_value(self, decoder=identity_decoder):
        return [ self.values[i].node_value(decoder) for i in range(self.num) ]

    def dict_value(self, decoder=identity_decoder):
        return { self.keys[i].decode('utf-8'):
                self.values[i].node_value(decoder) for i in range(self.num) }

class MpvByteArray(Structure):
    _fields_ = [('data', c_void_p),
                ('size', c_size_t)]

    def bytes_value(self):
        return cast(self.data, POINTER(c_char))[:self.size]

class MpvNode(Structure):
    def node_value(self, decoder=identity_decoder):
        return MpvNode.node_cast_value(self.val, self.format.value, decoder)

    @staticmethod
    def node_cast_value(v, fmt=MpvFormat.NODE, decoder=identity_decoder):
        if fmt == MpvFormat.NONE:
            return None
        elif fmt == MpvFormat.STRING:
            return decoder(v.string)
        elif fmt == MpvFormat.OSD_STRING:
            return v.string.decode('utf-8')
        elif fmt == MpvFormat.FLAG:
            return bool(v.flag)
        elif fmt == MpvFormat.INT64:
            return v.int64
        elif fmt == MpvFormat.DOUBLE:
            return v.double
        else:
            if not v.node: 
                return None
            if fmt == MpvFormat.NODE:
                return v.node.contents.node_value(decoder)
            elif fmt == MpvFormat.NODE_ARRAY:
                return v.list.contents.array_value(decoder)
            elif fmt == MpvFormat.NODE_MAP:
                return v.map.contents.dict_value(decoder)
            elif fmt == MpvFormat.BYTE_ARRAY:
                return v.byte_array.contents.bytes_value()
            else:
                raise TypeError('Unknown MPV node format {}. Please submit a bug report.'.format(fmt))

class MpvNodeUnion(Union):
    _fields_ = [('string', c_char_p),
                ('flag', c_int),
                ('int64', c_int64),
                ('double', c_double),
                ('node', POINTER(MpvNode)),
                ('list', POINTER(MpvNodeList)),
                ('map', POINTER(MpvNodeList)),
                ('byte_array', POINTER(MpvByteArray))]

MpvNode._fields_ = [('val', MpvNodeUnion),
                    ('format', MpvFormat)]

MpvNodeList._fields_ = [('num', c_int),
                        ('values', POINTER(MpvNode)),
                        ('keys', POINTER(c_char_p))]

class MpvSubApi(c_int):
    MPV_SUB_API_OPENGL_CB   = 1

class MpvEvent(Structure):
    _fields_ = [('event_id', MpvEventID),
                ('error', c_int),
                ('reply_userdata', c_ulonglong),
                ('data', c_void_p)]

    def as_dict(self, decoder=identity_decoder):
        dtype = {MpvEventID.END_FILE:               MpvEventEndFile,
                MpvEventID.PROPERTY_CHANGE:         MpvEventProperty,
                MpvEventID.GET_PROPERTY_REPLY:      MpvEventProperty,
                MpvEventID.LOG_MESSAGE:             MpvEventLogMessage,
                MpvEventID.SCRIPT_INPUT_DISPATCH:   MpvEventScriptInputDispatch,
                MpvEventID.CLIENT_MESSAGE:          MpvEventClientMessage
            }.get(self.event_id.value, None)
        return {'event_id': self.event_id.value,
                'error': self.error,
                'reply_userdata': self.reply_userdata,
                'event': cast(self.data, POINTER(dtype)).contents.as_dict(decoder=decoder) if dtype else None}

class MpvEventProperty(Structure):
    _fields_ = [('name', c_char_p),
                ('format', MpvFormat),
                ('data', MpvNodeUnion)]
    def as_dict(self, decoder=identity_decoder):
        value = MpvNode.node_cast_value(self.data, self.format.value, decoder)
        return {'name': self.name.decode('utf-8'),
                'format': self.format,
                'data': self.data,
                'value': value}

class MpvEventLogMessage(Structure):
    _fields_ = [('prefix', c_char_p),
                ('level', c_char_p),
                ('text', c_char_p)]

    def as_dict(self, decoder=identity_decoder):
        return { 'prefix': self.prefix.decode('utf-8'),
                 'level':  self.level.decode('utf-8'),
                 'text':   decoder(self.text).rstrip() }

class MpvEventEndFile(Structure):
    _fields_ = [('reason', c_int),
                ('error', c_int)]

    EOF                 = 0
    RESTARTED           = 1
    ABORTED             = 2
    QUIT                = 3
    ERROR               = 4
    REDIRECT            = 5

    # For backwards-compatibility
    @property
    def value(self):
        return self.reason

    def as_dict(self, decoder=identity_decoder):
        return {'reason': self.reason, 'error': self.error}

class MpvEventScriptInputDispatch(Structure):
    _fields_ = [('arg0', c_int),
                ('type', c_char_p)]

    def as_dict(self, decoder=identity_decoder):
        pass # TODO

class MpvEventClientMessage(Structure):
    _fields_ = [('num_args', c_int),
                ('args', POINTER(c_char_p))]

    def as_dict(self, decoder=identity_decoder):
        return { 'args': [ self.args[i].decode('utf-8') for i in range(self.num_args) ] }

StreamReadFn = CFUNCTYPE(c_int64, c_void_p, POINTER(c_char), c_uint64)
StreamSeekFn = CFUNCTYPE(c_int64, c_void_p, c_int64)
StreamSizeFn = CFUNCTYPE(c_int64, c_void_p)
StreamCloseFn = CFUNCTYPE(None, c_void_p)
StreamCancelFn = CFUNCTYPE(None, c_void_p)

class StreamCallbackInfo(Structure):
    _fields_ = [('cookie', c_void_p),
                ('read', StreamReadFn),
                ('seek', StreamSeekFn),
                ('size', StreamSizeFn),
                ('close', StreamCloseFn), ]
#                ('cancel', StreamCancelFn)]

StreamOpenFn = CFUNCTYPE(c_int, c_void_p, c_char_p, POINTER(StreamCallbackInfo))

WakeupCallback = CFUNCTYPE(None, c_void_p)

OpenGlCbUpdateFn = CFUNCTYPE(None, c_void_p)
OpenGlCbGetProcAddrFn = CFUNCTYPE(c_void_p, c_void_p, c_char_p)

def _handle_func(name, args, restype, errcheck, ctx=MpvHandle):
    func = getattr(backend, name)
    func.argtypes = [ctx] + args if ctx else args
    if restype is not None:
        func.restype = restype
    if errcheck is not None:
        func.errcheck = errcheck
    globals()['_'+name] = func

def bytes_free_errcheck(res, func, *args):
    notnull_errcheck(res, func, *args)
    rv = cast(res, c_void_p).value
    _mpv_free(res)
    return rv

def notnull_errcheck(res, func, *args):
    if res is None:
        raise RuntimeError('Underspecified error in MPV when calling {} with args {!r}: NULL pointer returned.'\
                'Please consult your local debugger.'.format(func.__name__, args))
    return res

ec_errcheck = ErrorCode.raise_for_ec

def _handle_gl_func(name, args=[], restype=None):
    _handle_func(name, args, restype, errcheck=None, ctx=MpvOpenGLCbContext)

backend.mpv_client_api_version.restype = c_ulong
def _mpv_client_api_version():
    ver = backend.mpv_client_api_version()
    return ver>>16, ver&0xFFFF

backend.mpv_free.argtypes = [c_void_p]
_mpv_free = backend.mpv_free

backend.mpv_free_node_contents.argtypes = [c_void_p]
_mpv_free_node_contents = backend.mpv_free_node_contents

backend.mpv_create.restype = MpvHandle
_mpv_create = backend.mpv_create

_handle_func('mpv_create_client',           [c_char_p],                                 MpvHandle, notnull_errcheck)
_handle_func('mpv_client_name',             [],                                         c_char_p, errcheck=None)
_handle_func('mpv_initialize',              [],                                         c_int, ec_errcheck)
_handle_func('mpv_detach_destroy',          [],                                         None, errcheck=None)
_handle_func('mpv_terminate_destroy',       [],                                         None, errcheck=None)
_handle_func('mpv_load_config_file',        [c_char_p],                                 c_int, ec_errcheck)
_handle_func('mpv_get_time_us',             [],                                         c_ulonglong, errcheck=None)

_handle_func('mpv_set_option',              [c_char_p, MpvFormat, c_void_p],            c_int, ec_errcheck)
_handle_func('mpv_set_option_string',       [c_char_p, c_char_p],                       c_int, ec_errcheck)

_handle_func('mpv_command',                 [POINTER(c_char_p)],                        c_int, ec_errcheck)
_handle_func('mpv_command_string',          [c_char_p, c_char_p],                       c_int, ec_errcheck)
_handle_func('mpv_command_async',           [c_ulonglong, POINTER(c_char_p)],           c_int, ec_errcheck)
_handle_func('mpv_command_node',            [POINTER(MpvNode), POINTER(MpvNode)],       c_int, ec_errcheck)
_handle_func('mpv_command_async',           [c_ulonglong, POINTER(MpvNode)],            c_int, ec_errcheck)

_handle_func('mpv_set_property',            [c_char_p, MpvFormat, c_void_p],            c_int, ec_errcheck)
_handle_func('mpv_set_property_string',     [c_char_p, c_char_p],                       c_int, ec_errcheck)
_handle_func('mpv_set_property_async',      [c_ulonglong, c_char_p, MpvFormat,c_void_p],c_int, ec_errcheck)
_handle_func('mpv_get_property',            [c_char_p, MpvFormat, c_void_p],            c_int, ec_errcheck)
_handle_func('mpv_get_property_string',     [c_char_p],                                 c_void_p, bytes_free_errcheck)
_handle_func('mpv_get_property_osd_string', [c_char_p],                                 c_void_p, bytes_free_errcheck)
_handle_func('mpv_get_property_async',      [c_ulonglong, c_char_p, MpvFormat],         c_int, ec_errcheck)
_handle_func('mpv_observe_property',        [c_ulonglong, c_char_p, MpvFormat],         c_int, ec_errcheck)
_handle_func('mpv_unobserve_property',      [c_ulonglong],                              c_int, ec_errcheck)

_handle_func('mpv_event_name',              [c_int],                                    c_char_p, errcheck=None, ctx=None)
_handle_func('mpv_error_string',            [c_int],                                    c_char_p, errcheck=None, ctx=None)

_handle_func('mpv_request_event',           [MpvEventID, c_int],                        c_int, ec_errcheck)
_handle_func('mpv_request_log_messages',    [c_char_p],                                 c_int, ec_errcheck)
_handle_func('mpv_wait_event',              [c_double],                                 POINTER(MpvEvent), errcheck=None)
_handle_func('mpv_wakeup',                  [],                                         None, errcheck=None)
_handle_func('mpv_set_wakeup_callback',     [WakeupCallback, c_void_p],                 None, errcheck=None)
_handle_func('mpv_get_wakeup_pipe',         [],                                         c_int, errcheck=None)

_handle_func('mpv_stream_cb_add_ro',        [c_char_p, c_void_p, StreamOpenFn],         c_int, ec_errcheck)

_handle_func('mpv_get_sub_api',             [MpvSubApi],                                c_void_p, notnull_errcheck)

_handle_gl_func('mpv_opengl_cb_set_update_callback',    [OpenGlCbUpdateFn, c_void_p])
_handle_gl_func('mpv_opengl_cb_init_gl',                [c_char_p, OpenGlCbGetProcAddrFn, c_void_p],    c_int)
_handle_gl_func('mpv_opengl_cb_draw',                   [c_int, c_int, c_int],                          c_int)
_handle_gl_func('mpv_opengl_cb_render',                 [c_int, c_int],                                 c_int)
_handle_gl_func('mpv_opengl_cb_report_flip',            [c_ulonglong],                                  c_int)
_handle_gl_func('mpv_opengl_cb_uninit_gl',              [],                                             c_int)


def _mpv_coax_proptype(value, proptype=str):
    if type(value) is bytes:
        return value;
    elif type(value) is bool:
        return b'yes' if value else b'no'
    elif proptype in (str, int, float):
        return str(proptype(value)).encode('utf-8')
    else:
        raise TypeError('Cannot coax value of type {} into property type {}'.format(type(value), proptype))

def _make_node_str_list(l):
    char_ps = [ c_char_p(_mpv_coax_proptype(e, str)) for e in l ]
    node_list = MpvNodeList(
        num=len(l),
        keys=None,
        values=( MpvNode * len(l))( *[ MpvNode(
                format=MpvFormat.STRING,
                val=MpvNodeUnion(string=p))
            for p in char_ps ]))
    node = MpvNode(
        format=MpvFormat.NODE_ARRAY,
        val=MpvNodeUnion(list=pointer(node_list)))
    return char_ps, node_list, node, cast(pointer(node), c_void_p)


def _event_generator(handle):
    while True:
        event = _mpv_wait_event(handle, -1).contents
        if event.event_id.value == MpvEventID.NONE:
            raise StopIteration()
        yield event


def _event_loop(event_handle, playback_cond, event_callbacks, message_handlers, property_handlers, log_handler):
    for event in _event_generator(event_handle):
        try:
            devent = event.as_dict(decoder=lazy_decoder)
            eid = devent['event_id']
            for callback in event_callbacks:
                callback(devent)
            if eid in (MpvEventID.SHUTDOWN, MpvEventID.END_FILE):
                with playback_cond:
                    playback_cond.notify_all()
            if eid == MpvEventID.PROPERTY_CHANGE:
                pc = devent['event']
                name, value, _fmt = pc['name'], pc['value'], pc['format']

                for handler in property_handlers[name]:
                    handler(name, value)
            if eid == MpvEventID.LOG_MESSAGE and log_handler is not None:
                ev = devent['event']
                log_handler(ev['level'], ev['prefix'], ev['text'])
            if eid == MpvEventID.CLIENT_MESSAGE:
                target, *args = devent['event']['args']
                if target in message_handlers:
                    message_handlers[target](*args)
            if eid == MpvEventID.SHUTDOWN:
                _mpv_detach_destroy(event_handle)
                return
        except Exception as e:
            traceback.print_exc()

_py_to_mpv = lambda name: name.replace('_', '-')
_mpv_to_py = lambda name: name.replace('-', '_')

class _Proxy:
    def __init__(self, mpv):
        super().__setattr__('mpv', mpv)

class _PropertyProxy(_Proxy):
    def __dir__(self):
        return super().__dir__() + [ name.replace('-', '_') for name in self.mpv.property_list ]

class _FileLocalProxy(_Proxy):
    def __getitem__(self, name):
        return self.mpv.__getitem__(name, file_local=True)

    def __setitem__(self, name, value):
        return self.mpv.__setitem__(name, value, file_local=True)

    def __iter__(self):
        return iter(self.mpv)

class _OSDPropertyProxy(_PropertyProxy):
    def __getattr__(self, name):
        return self.mpv._get_property(_py_to_mpv(name), fmt=MpvFormat.OSD_STRING)

    def __setattr__(self, _name, _value):
        raise AttributeError('OSD properties are read-only. Please use the regular property API for writing.')

class _DecoderPropertyProxy(_PropertyProxy):
    def __init__(self, mpv, decoder):
        super().__init__(mpv)
        super().__setattr__('_decoder', decoder)

    def __getattr__(self, name):
        return self.mpv._get_property(_py_to_mpv(name), decoder=self._decoder)

    def __setattr__(self, name, value):
        setattr(self.mpv, _py_to_mpv(name), value)

class GeneratorStream:

    def __init__(self, generator_fun, size=None):
        self._generator_fun = generator_fun
        self.size = size

    def seek(self, offset):
        self._read_iter = iter(self._generator_fun())
        self._read_chunk = b''
        return 0

    def read(self, size):
        if not self._read_chunk:
            try:
                self._read_chunk += next(self._read_iter)
            except StopIteration:
                return b''
        rv, self._read_chunk = self._read_chunk[:size], self._read_chunk[size:]
        return rv

    def close(self):
        self._read_iter = iter([]) 

    def cancel(self):
        self._read_iter = iter([])

class MPV(object):
    def __init__(self, *extra_mpv_flags, log_handler=None, start_event_thread=True, loglevel=None, **extra_mpv_opts):

        self.handle = _mpv_create()
        self._event_thread = None

        _mpv_set_option_string(self.handle, b'audio-display', b'no')
        istr = lambda o: ('yes' if o else 'no') if type(o) is bool else str(o)
        try:
            for flag in extra_mpv_flags:
                _mpv_set_option_string(self.handle, flag.encode('utf-8'), b'')
            for k,v in extra_mpv_opts.items():
                _mpv_set_option_string(self.handle, k.replace('_', '-').encode('utf-8'), istr(v).encode('utf-8'))
        finally:
            _mpv_initialize(self.handle)

        self.osd = _OSDPropertyProxy(self)
        self.file_local = _FileLocalProxy(self)
        self.raw    = _DecoderPropertyProxy(self, identity_decoder)
        self.strict = _DecoderPropertyProxy(self, strict_decoder)
        self.lazy   = _DecoderPropertyProxy(self, lazy_decoder)

        self._event_callbacks = []
        self._property_handlers = collections.defaultdict(lambda: [])
        self._message_handlers = {}
        self._key_binding_handlers = {}
        self._playback_cond = threading.Condition()
        self._event_handle = _mpv_create_client(self.handle, b'py_event_handler')
        self._loop = partial(_event_loop, self._event_handle, self._playback_cond, self._event_callbacks,
                self._message_handlers, self._property_handlers, log_handler)
        self._stream_protocol_cbs = {}
        self._stream_protocol_frontends = collections.defaultdict(lambda: {})
        self.register_stream_protocol('python', self._python_stream_open)
        self._python_streams = {}
        self._python_stream_catchall = None
        if loglevel is not None or log_handler is not None:
            self.set_loglevel(loglevel or 'terminal-default')
        if start_event_thread:
            self._event_thread = threading.Thread(target=self._loop, name='MPVEventHandlerThread')
            self._event_thread.setDaemon(True)
            self._event_thread.start()
        else:
            self._event_thread = None

    def wait_for_playback(self):
        with self._playback_cond:
            self._playback_cond.wait()

    def wait_for_property(self, name, cond=lambda val: val, level_sensitive=True):
        sema = threading.Semaphore(value=0)
        def observer(name, val):
            if cond(val):
                sema.release()
        self.observe_property(name, observer)
        if not level_sensitive or not cond(getattr(self, name.replace('-', '_'))):
            sema.acquire()
        self.unobserve_property(name, observer)

    def __del__(self):
        if self.handle:
            self.terminate()

    def terminate(self):
        self.handle, handle = None, self.handle
        if threading.current_thread() is self._event_thread:
            grim_reaper = threading.Thread(target=lambda: _mpv_terminate_destroy(handle))
            grim_reaper.start()
        else:
            _mpv_terminate_destroy(handle)
            if self._event_thread:
                self._event_thread.join()

    def set_loglevel(self, level):
        _mpv_request_log_messages(self._event_handle, level.encode('utf-8'))

    def command(self, name, *args):
        args = [name.encode('utf-8')] + [ (arg if type(arg) is bytes else str(arg).encode('utf-8'))
                for arg in args if arg is not None ] + [None]
        _mpv_command(self.handle, (c_char_p*len(args))(*args))

    def node_command(self, name, *args, decoder=strict_decoder):
        _1, _2, _3, pointer = _make_node_str_list([name, *args])
        out = cast(create_string_buffer(sizeof(MpvNode)), POINTER(MpvNode))
        ppointer = cast(pointer, POINTER(MpvNode))
        _mpv_command_node(self.handle, ppointer, out)
        rv = out.contents.node_value(decoder=decoder)
        _mpv_free_node_contents(out)
        return rv

    def seek(self, amount, reference="relative", precision="default-precise"):
        self.command('seek', amount, reference, precision)

    def revert_seek(self):
        self.command('revert_seek');

    def frame_step(self):
        self.command('frame_step')

    def frame_back_step(self):
        self.command('frame_back_step')

    def property_add(self, name, value=1):
        self.command('add', name, value)

    def property_multiply(self, name, factor):
        self.command('multiply', name, factor)

    def cycle(self, name, direction='up'):
        self.command('cycle', name, direction)

    def screenshot(self, includes='subtitles', mode='single'):
        self.command('screenshot', includes, mode)

    def screenshot_to_file(self, filename, includes='subtitles'):
        self.command('screenshot_to_file', filename.encode(fs_enc), includes)

    def screenshot_raw(self, includes='subtitles'):
        from PIL import Image
        res = self.node_command('screenshot-raw', includes)
        if res['format'] != 'bgr0':
            raise ValueError('Screenshot in unknown format "{}". Currently, only bgr0 is supported.'
                    .format(res['format']))
        img = Image.frombytes('RGBA', (res['stride']//4, res['h']), res['data'])
        b,g,r,a = img.split()
        return Image.merge('RGB', (r,g,b))

    def playlist_next(self, mode='weak'):
        self.command('playlist_next', mode)

    def playlist_prev(self, mode='weak'):
        self.command('playlist_prev', mode)

    @staticmethod
    def _encode_options(options):
        return ','.join('{}={}'.format(str(key), str(val)) for key, val in options.items())

    def loadfile(self, filename, mode='replace', **options):
        self.command('loadfile', filename.encode(fs_enc), mode, MPV._encode_options(options))

    def loadlist(self, playlist, mode='replace'):
        self.command('loadlist', playlist.encode(fs_enc), mode)

    def playlist_clear(self):
        self.command('playlist_clear')

    def playlist_remove(self, index='current'):
        self.command('playlist_remove', index)

    def playlist_move(self, index1, index2):
        self.command('playlist_move', index1, index2)

    def run(self, command, *args):
        self.command('run', command, *args)

    def quit(self, code=None):
        self.command('quit', code)

    def quit_watch_later(self, code=None):
        self.command('quit_watch_later', code)

    def sub_add(self, filename):
        self.command('sub_add', filename.encode(fs_enc))

    def sub_remove(self, sub_id=None):
        self.command('sub_remove', sub_id)

    def sub_reload(self, sub_id=None):
        self.command('sub_reload', sub_id)

    def sub_step(self, skip):
        self.command('sub_step', skip)

    def sub_seek(self, skip):
        self.command('sub_seek', skip)

    def toggle_osd(self):
        self.command('osd')

    def show_text(self, string, duration='-1', level=None):
        self.command('show_text', string, duration, level)

    def show_progress(self):
        self.command('show_progress')

    def discnav(self, command):
        self.command('discnav', command)

    def write_watch_later_config(self):
        self.command('write_watch_later_config')

    def overlay_add(self, overlay_id, x, y, file_or_fd, offset, fmt, w, h, stride):
        self.command('overlay_add', overlay_id, x, y, file_or_fd, offset, fmt, w, h, stride)

    def overlay_remove(self, overlay_id):
        self.command('overlay_remove', overlay_id)

    def script_message(self, *args):
        self.command('script_message', *args)

    def script_message_to(self, target, *args):
        self.command('script_message_to', target, *args)

    def observe_property(self, name, handler):
        self._property_handlers[name].append(handler)
        _mpv_observe_property(self._event_handle, hash(name)&0xffffffffffffffff, name.encode('utf-8'), MpvFormat.NODE)

    def property_observer(self, name):
        def wrapper(fun):
            self.observe_property(name, fun)
            fun.unobserve_mpv_properties = lambda: self.unobserve_property(name, fun)
            return fun
        return wrapper

    def unobserve_property(self, name, handler):
        self._property_handlers[name].remove(handler)
        if not self._property_handlers[name]:
            _mpv_unobserve_property(self._event_handle, hash(name)&0xffffffffffffffff)

    def unobserve_all_properties(self, handler):
        for name in self._property_handlers:
            self.unobserve_property(name, handler)

    def register_message_handler(self, target, handler=None):
        self._register_message_handler_internal(target, handler)

    def _register_message_handler_internal(self, target, handler):
        self._message_handlers[target] = handler

    def unregister_message_handler(self, target_or_handler):
        if isinstance(target_or_handler, str):
            del self._message_handlers[target_or_handler]
        else:
            for key, val in self._message_handlers.items():
                if val == target_or_handler:
                    del self._message_handlers[key]

    def message_handler(self, target):
        def register(handler):
            self._register_message_handler_internal(target, handler)
            handler.unregister_mpv_messages = lambda: self.unregister_message_handler(handler)
            return handler
        return register

    def register_event_callback(self, callback):
        self._event_callbacks.append(callback)

    def unregister_event_callback(self, callback):
        self._event_callbacks.remove(callback)

    def event_callback(self, *event_types):
        def register(callback):
            types = [MpvEventID.from_str(t) if isinstance(t, str) else t for t in event_types] or MpvEventID.ANY
            @wraps(callback)
            def wrapper(event, *args, **kwargs):
                if event['event_id'] in types:
                    callback(event, *args, **kwargs)
            self._event_callbacks.append(wrapper)
            wrapper.unregister_mpv_events = partial(self.unregister_event_callback, wrapper)
            return wrapper
        return register

    @staticmethod
    def _binding_name(callback_or_cmd):
        return 'py_kb_{:016x}'.format(hash(callback_or_cmd)&0xffffffffffffffff)

    def on_key_press(self, keydef, mode='force'):

        def register(fun):
            @self.key_binding(keydef, mode)
            @wraps(fun)
            def wrapper(state='p-', name=None, char=None):
                if state[0] in ('d', 'p'):
                    fun()
            return wrapper
        return register

    def key_binding(self, keydef, mode='force'):
        def register(fun):
            fun.mpv_key_bindings = getattr(fun, 'mpv_key_bindings', []) + [keydef]
            def unregister_all():
                for keydef in fun.mpv_key_bindings:
                    self.unregister_key_binding(keydef)
            fun.unregister_mpv_key_bindings = unregister_all

            self.register_key_binding(keydef, fun, mode)
            return fun
        return register

    def register_key_binding(self, keydef, callback_or_cmd, mode='force'):
        if not re.match(r'(Shift+)?(Ctrl+)?(Alt+)?(Meta+)?(.|\w+)', keydef):
            raise ValueError('Invalid keydef. Expected format: [Shift+][Ctrl+][Alt+][Meta+]<key>\n'
                    '<key> is either the literal character the key produces (ASCII or Unicode character), or a '
                    'symbolic name (as printed by --input-keylist')
        binding_name = MPV._binding_name(keydef)
        if callable(callback_or_cmd):
            self._key_binding_handlers[binding_name] = callback_or_cmd
            self.register_message_handler('key-binding', self._handle_key_binding_message)
            self.command('define-section',
                    binding_name, '{} script-binding py_event_handler/{}'.format(keydef, binding_name), mode)
        elif isinstance(callback_or_cmd, str):
            self.command('define-section', binding_name, '{} {}'.format(keydef, callback_or_cmd), mode)
        else:
            raise TypeError('register_key_binding expects either an str with an mpv command or a python callable.')
        self.command('enable-section', binding_name, 'allow-hide-cursor+allow-vo-dragging')

    def _handle_key_binding_message(self, binding_name, key_state, key_name=None, key_char=None):
        self._key_binding_handlers[binding_name](key_state, key_name, key_char)

    def unregister_key_binding(self, keydef):
        binding_name = MPV._binding_name(keydef)
        self.command('disable-section', binding_name)
        self.command('define-section', binding_name, '')
        if binding_name in self._key_binding_handlers:
            del self._key_binding_handlers[binding_name]
            if not self._key_binding_handlers:
                self.unregister_message_handler('key-binding')

    def register_stream_protocol(self, proto, open_fn=None):

        def decorator(open_fn):
            @StreamOpenFn
            def open_backend(_userdata, uri, cb_info):
                try:
                    frontend = open_fn(uri.decode('utf-8'))
                except ValueError:
                    return ErrorCode.LOADING_FAILED

                def read_backend(_userdata, buf, bufsize):
                    data = frontend.read(bufsize)
                    for i in range(len(data)):
                        buf[i] = data[i]
                    return len(data)

                cb_info.contents.cookie = None
                read = cb_info.contents.read = StreamReadFn(read_backend)
                close = cb_info.contents.close = StreamCloseFn(lambda _userdata: frontend.close())

                seek, size, cancel = None, None, None
                if hasattr(frontend, 'seek'):
                    seek = cb_info.contents.seek = StreamSeekFn(lambda _userdata, offx: frontend.seek(offx))
                if hasattr(frontend, 'size') and frontend.size is not None:
                    size = cb_info.contents.size = StreamSizeFn(lambda _userdata: frontend.size)
                frontend._registered_callbacks = [read, close, seek, size, cancel]
                self._stream_protocol_frontends[proto][uri] = frontend
                return 0

            if proto in self._stream_protocol_cbs:
                raise KeyError('Stream protocol already registered')
            self._stream_protocol_cbs[proto] = [open_backend]
            _mpv_stream_cb_add_ro(self.handle, proto.encode('utf-8'), c_void_p(), open_backend)

            return open_fn

        if open_fn is not None:
            decorator(open_fn)
        return decorator

    def play(self, filename):
        self.loadfile(filename)

    @property
    def playlist_filenames(self):
        return [element['filename'] for element in self.playlist]

    def playlist_append(self, filename, **options):
        self.loadfile(filename, 'append', **options)

    def _python_stream_open(self, uri):
        name, = re.fullmatch('python://(.*)', uri).groups()

        if name in self._python_streams:
            generator_fun, size = self._python_streams[name]
        else:
            if self._python_stream_catchall is not None:
                generator_fun, size = self._python_stream_catchall(name)
            else:
                raise ValueError('Python stream name not found and no catch-all defined')

        return GeneratorStream(generator_fun, size)

    def python_stream(self, name=None, size=None):
        def register(cb):
            if name in self._python_streams:
                raise KeyError('Python stream name "{}" is already registered'.format(name))
            self._python_streams[name] = (cb, size)
            def unregister():
                if name not in self._python_streams or\
                        self._python_streams[name][0] is not cb: # This is just a basic sanity check
                    raise RuntimeError('Python stream has already been unregistered')
                del self._python_streams[name]
            cb.unregister = unregister
            return cb
        return register

    def python_stream_catchall(self, cb):
        if self._python_stream_catchall is not None:
            raise KeyError('A catch-all python stream is already registered')

        self._python_stream_catchall = cb
        def unregister():
            if self._python_stream_catchall is not cb:
                    raise RuntimeError('This catch-all python stream has already been unregistered')
            self._python_stream_catchall = None
        cb.unregister = unregister
        return cb
    def _get_property(self, name, decoder=strict_decoder, fmt=MpvFormat.NODE):
        out = create_string_buffer(sizeof(MpvNode))
        try:
            cval = _mpv_get_property(self.handle, name.encode('utf-8'), fmt, out)

            if fmt is MpvFormat.OSD_STRING:
                return cast(out, POINTER(c_char_p)).contents.value.decode('utf-8')
            elif fmt is MpvFormat.NODE:
                rv = cast(out, POINTER(MpvNode)).contents.node_value(decoder=decoder)
                _mpv_free_node_contents(out)
                return rv
            else:
                raise TypeError('_get_property only supports NODE and OSD_STRING formats.')
        except PropertyUnavailableError as ex:
            return None

    def _set_property(self, name, value):
        ename = name.encode('utf-8')
        if isinstance(value, (list, set, dict)):
            _1, _2, _3, pointer = _make_node_str_list(value)
            _mpv_set_property(self.handle, ename, MpvFormat.NODE, pointer)
        else:
            _mpv_set_property_string(self.handle, ename, _mpv_coax_proptype(value))

    def __getattr__(self, name):
        return self._get_property(_py_to_mpv(name), lazy_decoder)

    def __setattr__(self, name, value):
            try:
                if name != 'handle' and not name.startswith('_'):
                    self._set_property(_py_to_mpv(name), value)
                else:
                    super().__setattr__(name, value)
            except AttributeError:
                super().__setattr__(name, value)

    def __dir__(self):
        return super().__dir__() + [ name.replace('-', '_') for name in self.property_list ]

    @property
    def properties(self):
        return { name: self.option_info(name) for name in self.property_list }
    def __getitem__(self, name, file_local=False):
        prefix = 'file-local-options/' if file_local else 'options/'
        return self._get_property(prefix+name, lazy_decoder)

    def __setitem__(self, name, value, file_local=False):
        prefix = 'file-local-options/' if file_local else 'options/'
        return self._set_property(prefix+name, value)

    def __iter__(self):
        return iter(self.options)

    def option_info(self, name):
        try:
            return self._get_property('option-info/'+name)
        except AttributeError:
            return None

# End mpv.py module

def DesktopHWND():

    SendMessage(FindWindow("Progman", None), 0x052C, 0, 0)

    def CallBack(hwnd, enum):
        WorkerW = FindWindowEx(0, hwnd, "WorkerW", None)
        if FindWindowEx(hwnd, 0, "SHELLDLL_DefView", None) and WorkerW:
            enum.append(WorkerW)
            return
        return True

    enum = []
    EnumWindows(CallBack, enum)
    return enum[0]

def CheckFile(file):

    if path.isfile(file):
        return True
    return False

def KeyHook():

    hide = False
    hwnd = GetForegroundWindow()
    while 1:
        if GetAsyncKeyState(121) and hide:
            ShowWindow(hwnd, 5)
            hide = False
        elif GetAsyncKeyState(121) and hide == False:
            ShowWindow(hwnd, 0)
            hide = True
        sleep(.09)

logo = """
        ▄▄▌ ▐ ▄▌ ▄▄▄· ▄▄▌  ▄▄▌   ▄▄▄· ▄▄▄·  ▄▄▄·▄▄▄ .▄▄▄  
        ██· █▌▐█▐█ ▀█ ██•  ██•  ▐█ ▄█▐█ ▀█ ▐█ ▄█▀▄.▀·▀▄ █·
        ██▪▐█▐▐▌▄█▀▀█ ██▪  ██▪   ██▀·▄█▀▀█  ██▀·▐▀▀▪▄▐▀▀▄ 
        ▐█▌██▐█▌▐█ ▪▐▌▐█▌▐▌▐█▌▐▌▐█▪·•▐█ ▪▐▌▐█▪·•▐█▄▄▌▐█•█▌
         ▀▀▀▀ ▀▪ ▀  ▀ .▀▀▀ .▀▀▀ .▀    ▀  ▀ .▀    ▀▀▀ .▀  ▀
                ▄▄▄ . ▐ ▄  ▄▄ • ▪   ▐ ▄ ▄▄▄ .             
                ▀▄.▀·•█▌▐█▐█ ▀ ▪██ •█▌▐█▀▄.▀·             
                ▐▀▀▪▄▐█▐▐▌▄█ ▀█▄▐█·▐█▐▐▌▐▀▀▪▄             
                ▐█▄▄▌██▐█▌▐█▄▪▐█▐█▌██▐█▌▐█▄▄▌             
                 ▀▀▀ ▀▀ █▪·▀▀▀▀ ▀▀▀▀▀ █▪ ▀▀▀              
         ▄▄· ▄▄▌  ▪      • ▌ ▄ ·.       ·▄▄▄▄  ▄▄▄ .      
        ▐█ ▌▪██•  ██     ·██ ▐███▪▪     ██▪ ██ ▀▄.▀·      
        ██ ▄▄██▪  ▐█·    ▐█ ▌▐▌▐█· ▄█▀▄ ▐█· ▐█▌▐▀▀▪▄      
        ▐███▌▐█▌▐▌▐█▌    ██ ██▌▐█▌▐█▌.▐▌██. ██ ▐█▄▄▌      
        ·▀▀▀ .▀▀▀ ▀▀▀    ▀▀  █▪▀▀▀ ▀█▄▀▪▀▀▀▀▀•  ▀▀▀ \n
      [Wallpaper engine based on python-MPV and youtube-dl.]\n"""

def MPVThread(player):

    player.playlist_pos = 0
    for track in player.playlist:
        player.wait_for_playback()
