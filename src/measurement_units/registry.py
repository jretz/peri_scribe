"""Quantities remain compatible when libraries and the application share a registry."""

import pint


units = pint.UnitRegistry()

# Monetary observations share the same registry as physical measurements.
units.define("dollar = [currency] = $ = USD")
