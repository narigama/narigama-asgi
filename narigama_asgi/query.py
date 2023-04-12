import pypika


class Parameter(pypika.Parameter):
    def get_sql(self, **kwargs):
        if not isinstance(self.placeholder, str):
            raise TypeError(type(self.placeholder))
        return "{{{placeholder}}}".format(placeholder=self.placeholder)


def get_sql(query, params: dict | None = None):
    sql = str(query)
    params = params or {}
    indexes, args = {}, []

    # build indexes and args in correct order
    for index, key in enumerate(sorted(params.keys())):
        indexes[key] = "${}".format(index + 1)
        args.append(params[key])

    try:
        return sql.format_map(indexes), args
    except KeyError as ex:
        err = "Attepmting to build query: `{}`"
        raise Exception(err.format(sql)) from ex
