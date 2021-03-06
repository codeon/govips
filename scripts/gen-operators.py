#!/usr/bin/python

# Walk vips and generate member definitions for all operators
# based on libvips/gen-operators.py

import datetime
import logging
import re
import sys
from string import Template

import gi
gi.require_version('Vips', '8.0')
from gi.repository import Vips, GObject

vips_type_image = GObject.GType.from_name("VipsImage")
vips_type_operation = GObject.GType.from_name("VipsOperation")
param_enum = GObject.GType.from_name("GParamEnum")

today = datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y")

preamble ='''\
package vips

//golint:ignore

/***
 * NOTE: This file is autogenerated so you shouldn't modify it.
 * See scripts/gen-operators.py
 *
 * Generated at %s
 */

// #cgo pkg-config: vips
// #include "vips/vips.h"
import "C"\

// See http://www.vips.ecs.soton.ac.uk/supported/current/doc/html/libvips/func-list.html
''' % today

go_types = {
  "gboolean" : "bool",
  "gchararray" : "string",
  "gdouble" : "float64",
  "gint" : "int",
  "VipsBlob" : "*Blob",
  "VipsImage" : "*C.VipsImage",
  "VipsInterpolate": "*Interpolator",
  "VipsOperationMath" : "OperationMath",
  "VipsOperationMath2" : "OperationMath2",
  "VipsOperationRound" : "OperationRound",
  "VipsOperationRelational" : "OperationRelational",
  "VipsOperationBoolean" : "OperationBoolean",
  "VipsOperationComplex" : "OperationComplex",
  "VipsOperationComplex2" : "OperationComplex2",
  "VipsOperationComplexget" : "OperationComplexGet",
  "VipsDirection" : "Direction",
  "VipsAngle" : "Angle",
  "VipsAngle45" : "Angle45",
  "VipsCoding": "Coding",
  "VipsInterpretation": "Interpretation",
  "VipsBandFormat": "BandFormat",
  "VipsOperationMorphology": "OperationMorphology",
}

options_method_names = {
  "gboolean" : "Bool",
  "gchararray" : "String",
  "gdouble" : "Double",
  "gint" : "Int",
  "VipsArrayDouble" : "DoubleArray",
  "VipsArrayImage" : "ImageArray",
  "VipsImage" : "Image",
}


def get_type(prop):
  return go_types[prop.value_type.name]


def get_options_method_name(prop):
  # Enums use their values
  if GObject.type_is_a(param_enum, prop):
    return "Int"
  return options_method_names[prop.value_type.name]


def find_required(op):
  required = []
  for prop in op.props:
    flags = op.get_argument_flags(prop.name)
    if not flags & Vips.ArgumentFlags.REQUIRED:
      continue
    if flags & Vips.ArgumentFlags.DEPRECATED:
      continue
    required.append(prop)
  def priority_sort(a, b):
    pa = op.get_argument_priority(a.name)
    pb = op.get_argument_priority(b.name)
    return pa - pb
  required.sort(priority_sort)
  return required


# find the first output arg ... this will be used as the result
def find_first_output(op, required):
  found = False
  for prop in required:
    flags = op.get_argument_flags(prop.name)
    if not flags & Vips.ArgumentFlags.OUTPUT:
      continue
    found = True
    break

  if not found:
    return None

  return prop


def cppize(name):
  return re.sub('-', '_', name)


def upper_camelcase(name):
  if not name:
    return ''
  name = cppize(name)
  return ''.join(c for c in name.title() if not c.isspace() and c != '_')


def lower_camelcase(name):
  name = cppize(name)
  parts = name.split('_')
  return parts[0] + upper_camelcase(''.join(parts[1:]))


def gen_params(op, required):
  args = [];
  for prop in required:
    arg = lower_camelcase(prop.name) + ' '
    flags = op.get_argument_flags(prop.name)
    if flags & Vips.ArgumentFlags.OUTPUT:
      arg += '*'
    arg += get_type(prop)
    args.append(arg)
  args.append('opts ...OptionFunc')
  return ', '.join(args)


func_template = Template('''
// $func_name executes the '$op_name' operation
func $func_name($args) ($return_types) {
  $decls
  options = append(options,
    $input_options
    $output_options
  )
  incOpCounter("$op_name")
  err = vipsCall("$op_name", options)
  return $return_values
}
''')


stream_template = Template('''
// $func_name executes the '$op_name' operation
func (in *ImageRef) $func_name($method_args) error {
  out, err := $func_name(in.image, $call_values)
  if err != nil {
    return err
  }
  in.SetImage(out)
  return nil
}
''')


def emit_func(d):
  return func_template.substitute(d)


def emit_method(d):
  return stream_template.substitute(d)


def gen_operation(cls):
  op = Vips.Operation.new(cls.name)
  gtype = Vips.type_find("VipsOperation", cls.name)

  op_name = Vips.nickname_find(gtype)
  func_name = upper_camelcase(op_name)

  args = []
  decls = []
  return_types = []
  return_names = []
  return_values = []
  input_options = []
  output_options = []
  method_args = []
  call_values = []
  images_in = 0
  images_out = 0

  all_props = find_required(op)
  for prop in all_props:
    name = lower_camelcase(prop.name)
    prop_type = get_type(prop)
    flags = op.get_argument_flags(prop.name)
    method_name = get_options_method_name(prop)

    if flags & Vips.ArgumentFlags.OUTPUT:
      if GObject.type_is_a(vips_type_image, prop.value_type):
        images_out += 1
      else:
        method_args.append('%s *%s' % (name, prop_type))
      return_types.append(prop_type)
      decls.append('var %s %s' % (name, prop_type))
      return_values.append(name)
      output_options.append('Output%s("%s", &%s),' % (method_name, prop.name, name))
    else:
      if GObject.type_is_a(vips_type_image, prop.value_type):
        images_in += 1
      else:
        call_values.append(name)
        method_args.append('%s %s' % (name, prop_type))
      args.append('%s %s' % (name, prop_type))
      arg_name = name
      if GObject.type_is_a(param_enum, prop):
        arg_name = 'int(%s)' % arg_name
      input_options.append('Input%s("%s", %s),' % (method_name, prop.name, arg_name))

  args.append('options ...*Option')
  decls.append('var err error')
  return_types.append('error')
  return_values.append('err')
  method_args.append('options ...*Option')
  call_values.append('options...')

  funcs = []

  d = {
    'op_name': op_name,
    'func_name': func_name,
    'args': ', '.join(args),
    'decls': '\n\t'.join(decls),
    'input_options': '\n\t\t'.join(input_options),
    'output_options': '\n\t\t'.join(output_options),
    'return_types': ', '.join(return_types),
    'return_values': ', '.join(return_values),
  }

  funcs.append(emit_func(d))

  if images_in == 1 and images_out == 1:
    d['method_args'] = ', '.join(method_args)
    d['call_values'] = ', '.join(call_values)
    funcs.append(emit_method(d))

  return '\n'.join(funcs)


# we have a few synonyms ... don't generate twice
generated = {}


def find_class_methods(cls):
  methods = []
  skipped = []
  if not cls.is_abstract():
    gtype = Vips.type_find("VipsOperation", cls.name)
    nickname = Vips.nickname_find(gtype)
    if not nickname in generated:
      try:
        methods.append(gen_operation(cls))
        generated[nickname] = True
      except Exception as e:
        skipped.append('// Unsupported: %s: %s' % (nickname, str(e)))
  if len(cls.children) > 0:
    for child in cls.children:
      m, s = find_class_methods(child)
      methods.extend(m)
      skipped.extend(s)
  return methods, skipped


def generate_file():
  methods, skipped = find_class_methods(vips_type_operation)
  methods.sort()
  skipped.sort()
  output = '%s\n\n' % preamble
  if len(skipped) > 0:
    output += '%s\n\n' % '\n'.join(skipped)
  output += '\n\n'.join(methods)
  print(output)


if __name__ == '__main__':
  generate_file()
