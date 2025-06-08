# coding: utf-8
import sys

from django.core.cache import cache
from django.db.models import Field

if sys.version_info >= (3, ):
    from django.utils.encoding import force_str as force_text
else:
    from django.utils.encoding import force_text


def get_model_name(model):
    """
    Returns the name of the model
    """
    return model._meta.model_name


def replace_from_choices(choices):
    def inner(values):
        return [choices.get(v, v) for v in values]
    return inner


def get_base_cache_key(model):
    return 'pandas_%s_%s_%%s_rendering' % (
        model._meta.app_label, get_model_name(model))


def get_cache_key(obj):
    return get_base_cache_key(obj._meta.model) % obj.pk


def invalidate(obj):
    cache.delete(get_cache_key(obj))


def invalidate_signal_handler(sender, **kwargs):
    invalidate(kwargs['instance'])


def get_to_field(field):
    tof = field.to_fields[0] if field.to_fields else None
    return tof or 'pk'


def replace_fk(model, to_field='pk'):
    base_cache_key = get_base_cache_key(model)

    def get_cache_key_from_value(val):
        if val is None:
            return None
        else:
            try:
                intVal = int(val)
                return base_cache_key % intVal
            except:
                return base_cache_key % val

    def inner(value_series):
        value_series = value_series.astype(object).where(value_series.notnull(), None)
        cache_keys = value_series.apply(get_cache_key_from_value)
        unique_cache_keys = list(filter(None, cache_keys.unique()))

        if not unique_cache_keys:
            return value_series

        out_dict = cache.get_many(unique_cache_keys)

        if len(out_dict) < len(unique_cache_keys):
            values = list(filter(None, value_series.unique()))
            objs = model.objects.filter(**{f"{to_field}__in": values})
            out_dict = {
                base_cache_key % getattr(obj, to_field): force_text(obj)
                for obj in objs
            }
            cache.set_many(out_dict)

        return list(map(out_dict.get, cache_keys))

    return inner


def build_update_functions(fieldnames, fields):
    for fieldname, field in zip(fieldnames, fields):
        if not isinstance(field, Field):
            yield fieldname, None
        else:
            if field and field.choices:
                choices = dict([(k, force_text(v))
                                for k, v in field.flatchoices])
                yield fieldname, replace_from_choices(choices)

            elif field and field.get_internal_type() == 'ForeignKey':
                yield fieldname, replace_fk(get_related_model(field), to_field=get_to_field(field))


def update_with_verbose(df, fieldnames, fields):
    for fieldname, function in build_update_functions(fieldnames, fields):
        if function is not None:
            df[fieldname] = function(df[fieldname])


def get_related_model(field):
    """Gets the related model from a related field"""
    model = None

    if hasattr(field, 'related_model') and field.related_model:   #  pragma: no cover
        model = field.related_model
    # Django<1.8 doesn't have the related_model API, so we need to use rel,
    # which was removed in Django 2.0
    elif hasattr(field, 'rel') and field.rel:  # pragma: no cover
        model = field.rel.to

    return model
