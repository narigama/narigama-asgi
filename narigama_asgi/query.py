import pypika


class Parameter(pypika.Parameter):
    """
    Use to generate named params.

    Pass the resultant query to `get_sql`, to build the query and args.
    """

    def get_sql(self, **kwargs):
        if not isinstance(self.placeholder, str):
            raise TypeError(type(self.placeholder))
        return "{{{placeholder}}}".format(placeholder=self.placeholder)


def get_sql(query, params: dict | None = None):
    """
    Given a pypika query with params generated using the above custom class to
    generate Parameters, build an SQL query and args.
    """
    sql = str(query)
    params = params or {}
    indexes = {}
    args = []

    # build indexes and args in correct order
    for index, key in enumerate(sorted(params.keys())):
        indexes[key] = "${}".format(index + 1)
        args.append(params[key])

    # now map the indexes to the query
    try:
        return sql.format_map(indexes), args

    except KeyError as ex:
        err = "Attempting to build query: `{}`"
        raise Exception(err.format(sql)) from ex
