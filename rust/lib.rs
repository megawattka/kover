// I am using this as my template for rust extensions.

use std::ffi::c_int;
use std::os::raw::c_void;
use std::ptr::{self, null_mut};

use pyo3::ffi::{
    METH_VARARGS,
    Py_mod_exec,
    PyArg_ParseTuple,
    PyDateTime_IMPORT,
    PyDateTimeAPI,
    PyErr_SetString,
    PyExc_ImportError,
    PyLong_FromLong,
    PyMethodDef,
    PyMethodDefPointer,
    PyModule_GetState,
    PyModuleDef,
    PyModuleDef_HEAD_INIT,
    PyModuleDef_Init,
    PyModuleDef_Slot,
    PyObject,
    c_str
};

#[repr(C)]
pub(crate) struct ModuleState {}

#[inline(always)]
pub(crate) unsafe fn get_state(module: *mut PyObject) -> *mut ModuleState {
    PyModule_GetState(module) as *mut ModuleState
}

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c_str!("rlib").as_ptr(),
    m_doc: c_str!("Kover rust extension.").as_ptr(),
    m_size: size_of::<ModuleState>() as isize,
    m_methods: unsafe { METHODS as *const [PyMethodDef] as *mut PyMethodDef },
    m_slots: unsafe { SLOTS as *const [PyModuleDef_Slot] as *mut PyModuleDef_Slot },
    m_traverse: None,
    m_clear: None,
    m_free: None,
};

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("add_numbers").as_ptr(),
        ml_meth: PyMethodDefPointer {
            PyCFunction: add_numbers,
        },
        ml_flags: METH_VARARGS,
        ml_doc: null_mut(),
    },
    // A zeroed PyMethodDef to mark the end of the array.
    PyMethodDef::zeroed(),
];


#[inline(always)]
pub unsafe fn _rlib_exec(module: *mut PyObject) -> c_int {
    PyDateTime_IMPORT();
    if PyDateTimeAPI().is_null() {
        PyErr_SetString(
            PyExc_ImportError,
            c_str!("Could not import datetime C API").as_ptr(),
        );
        return 1;
    }
    let _state = get_state(module);
    // here setting state fields by dereferencing it

    return 0;
}

static mut SLOTS: &[PyModuleDef_Slot] = &[
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: _rlib_exec as *mut c_void
    },
    PyModuleDef_Slot {
        slot: 0,
        value: std::ptr::null_mut(),
    },
];

#[no_mangle]
pub unsafe extern "C" fn PyInit_rlib() -> *mut PyObject {
    PyModuleDef_Init(ptr::addr_of_mut!(MODULE_DEF))
}

pub unsafe extern "C" fn add_numbers(
    _module: *mut PyObject,
    args: *mut PyObject,
) -> *mut PyObject {
    let mut a: i64 = 0;
    let mut b: i64 = 0;
    if PyArg_ParseTuple(args, c_str!("ii").as_ptr(), &mut a, &mut b) != 1 {
        return ptr::null_mut();  // raises TypeError on failure
    }
    PyLong_FromLong(a + b)
}