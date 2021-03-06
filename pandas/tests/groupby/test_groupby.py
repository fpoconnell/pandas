# -*- coding: utf-8 -*-
from __future__ import print_function

import pytest

from warnings import catch_warnings
from datetime import datetime

from pandas import (date_range, bdate_range, Timestamp,
                    Index, MultiIndex, DataFrame, Series,
                    concat, Panel, DatetimeIndex, read_csv)
from pandas.errors import UnsupportedFunctionCall, PerformanceWarning
from pandas.util.testing import (assert_frame_equal, assert_index_equal,
                                 assert_series_equal, assert_almost_equal)
from pandas.compat import (range, lrange, StringIO, lmap, lzip, map, zip,
                           builtins, OrderedDict)
from pandas import compat
from collections import defaultdict
import pandas.core.common as com
import numpy as np

import pandas.core.nanops as nanops
import pandas.util.testing as tm
import pandas as pd
from .common import MixIn


class TestGrouper(object):

    def test_repr(self):
        # GH18203
        result = repr(pd.Grouper(key='A', level='B'))
        expected = "Grouper(key='A', level='B', axis=0, sort=False)"
        assert result == expected


class TestGroupBy(MixIn):

    def test_basic(self):
        def checkit(dtype):
            data = Series(np.arange(9) // 3, index=np.arange(9), dtype=dtype)

            index = np.arange(9)
            np.random.shuffle(index)
            data = data.reindex(index)

            grouped = data.groupby(lambda x: x // 3)

            for k, v in grouped:
                assert len(v) == 3

            agged = grouped.aggregate(np.mean)
            assert agged[1] == 1

            assert_series_equal(agged, grouped.agg(np.mean))  # shorthand
            assert_series_equal(agged, grouped.mean())
            assert_series_equal(grouped.agg(np.sum), grouped.sum())

            expected = grouped.apply(lambda x: x * x.sum())
            transformed = grouped.transform(lambda x: x * x.sum())
            assert transformed[7] == 12
            assert_series_equal(transformed, expected)

            value_grouped = data.groupby(data)
            assert_series_equal(value_grouped.aggregate(np.mean), agged,
                                check_index_type=False)

            # complex agg
            agged = grouped.aggregate([np.mean, np.std])

            with tm.assert_produces_warning(FutureWarning,
                                            check_stacklevel=False):
                agged = grouped.aggregate({'one': np.mean, 'two': np.std})

            group_constants = {0: 10, 1: 20, 2: 30}
            agged = grouped.agg(lambda x: group_constants[x.name] + x.mean())
            assert agged[1] == 21

            # corner cases
            pytest.raises(Exception, grouped.aggregate, lambda x: x * 2)

        for dtype in ['int64', 'int32', 'float64', 'float32']:
            checkit(dtype)

    def test_groupby_nonobject_dtype(self):
        key = self.mframe.index.labels[0]
        grouped = self.mframe.groupby(key)
        result = grouped.sum()

        expected = self.mframe.groupby(key.astype('O')).sum()
        assert_frame_equal(result, expected)

        # GH 3911, mixed frame non-conversion
        df = self.df_mixed_floats.copy()
        df['value'] = lrange(len(df))

        def max_value(group):
            return group.loc[group['value'].idxmax()]

        applied = df.groupby('A').apply(max_value)
        result = applied.get_dtype_counts().sort_values()
        expected = Series({'object': 2,
                           'float64': 2,
                           'int64': 1}).sort_values()
        assert_series_equal(result, expected)

    def test_groupby_return_type(self):

        # GH2893, return a reduced type
        df1 = DataFrame(
            [{"val1": 1, "val2": 20},
             {"val1": 1, "val2": 19},
             {"val1": 2, "val2": 27},
             {"val1": 2, "val2": 12}
             ])

        def func(dataf):
            return dataf["val2"] - dataf["val2"].mean()

        result = df1.groupby("val1", squeeze=True).apply(func)
        assert isinstance(result, Series)

        df2 = DataFrame(
            [{"val1": 1, "val2": 20},
             {"val1": 1, "val2": 19},
             {"val1": 1, "val2": 27},
             {"val1": 1, "val2": 12}
             ])

        def func(dataf):
            return dataf["val2"] - dataf["val2"].mean()

        result = df2.groupby("val1", squeeze=True).apply(func)
        assert isinstance(result, Series)

        # GH3596, return a consistent type (regression in 0.11 from 0.10.1)
        df = DataFrame([[1, 1], [1, 1]], columns=['X', 'Y'])
        result = df.groupby('X', squeeze=False).count()
        assert isinstance(result, DataFrame)

        # GH5592
        # inconcistent return type
        df = DataFrame(dict(A=['Tiger', 'Tiger', 'Tiger', 'Lamb', 'Lamb',
                               'Pony', 'Pony'], B=Series(
                                   np.arange(7), dtype='int64'), C=date_range(
                                       '20130101', periods=7)))

        def f(grp):
            return grp.iloc[0]

        expected = df.groupby('A').first()[['B']]
        result = df.groupby('A').apply(f)[['B']]
        assert_frame_equal(result, expected)

        def f(grp):
            if grp.name == 'Tiger':
                return None
            return grp.iloc[0]

        result = df.groupby('A').apply(f)[['B']]
        e = expected.copy()
        e.loc['Tiger'] = np.nan
        assert_frame_equal(result, e)

        def f(grp):
            if grp.name == 'Pony':
                return None
            return grp.iloc[0]

        result = df.groupby('A').apply(f)[['B']]
        e = expected.copy()
        e.loc['Pony'] = np.nan
        assert_frame_equal(result, e)

        # 5592 revisited, with datetimes
        def f(grp):
            if grp.name == 'Pony':
                return None
            return grp.iloc[0]

        result = df.groupby('A').apply(f)[['C']]
        e = df.groupby('A').first()[['C']]
        e.loc['Pony'] = pd.NaT
        assert_frame_equal(result, e)

        # scalar outputs
        def f(grp):
            if grp.name == 'Pony':
                return None
            return grp.iloc[0].loc['C']

        result = df.groupby('A').apply(f)
        e = df.groupby('A').first()['C'].copy()
        e.loc['Pony'] = np.nan
        e.name = None
        assert_series_equal(result, e)

    def test_apply_issues(self):
        # GH 5788

        s = """2011.05.16,00:00,1.40893
2011.05.16,01:00,1.40760
2011.05.16,02:00,1.40750
2011.05.16,03:00,1.40649
2011.05.17,02:00,1.40893
2011.05.17,03:00,1.40760
2011.05.17,04:00,1.40750
2011.05.17,05:00,1.40649
2011.05.18,02:00,1.40893
2011.05.18,03:00,1.40760
2011.05.18,04:00,1.40750
2011.05.18,05:00,1.40649"""

        df = pd.read_csv(
            StringIO(s), header=None, names=['date', 'time', 'value'],
            parse_dates=[['date', 'time']])
        df = df.set_index('date_time')

        expected = df.groupby(df.index.date).idxmax()
        result = df.groupby(df.index.date).apply(lambda x: x.idxmax())
        assert_frame_equal(result, expected)

        # GH 5789
        # don't auto coerce dates
        df = pd.read_csv(
            StringIO(s), header=None, names=['date', 'time', 'value'])
        exp_idx = pd.Index(
            ['2011.05.16', '2011.05.17', '2011.05.18'
             ], dtype=object, name='date')
        expected = Series(['00:00', '02:00', '02:00'], index=exp_idx)
        result = df.groupby('date').apply(
            lambda x: x['time'][x['value'].idxmax()])
        assert_series_equal(result, expected)

    def test_time_field_bug(self):
        # Test a fix for the following error related to GH issue 11324 When
        # non-key fields in a group-by dataframe contained time-based fields
        # that were not returned by the apply function, an exception would be
        # raised.

        df = pd.DataFrame({'a': 1, 'b': [datetime.now() for nn in range(10)]})

        def func_with_no_date(batch):
            return pd.Series({'c': 2})

        def func_with_date(batch):
            return pd.Series({'c': 2, 'b': datetime(2015, 1, 1)})

        dfg_no_conversion = df.groupby(by=['a']).apply(func_with_no_date)
        dfg_no_conversion_expected = pd.DataFrame({'c': 2}, index=[1])
        dfg_no_conversion_expected.index.name = 'a'

        dfg_conversion = df.groupby(by=['a']).apply(func_with_date)
        dfg_conversion_expected = pd.DataFrame(
            {'b': datetime(2015, 1, 1),
             'c': 2}, index=[1])
        dfg_conversion_expected.index.name = 'a'

        tm.assert_frame_equal(dfg_no_conversion, dfg_no_conversion_expected)
        tm.assert_frame_equal(dfg_conversion, dfg_conversion_expected)

    def test_len(self):
        df = tm.makeTimeDataFrame()
        grouped = df.groupby([lambda x: x.year, lambda x: x.month,
                              lambda x: x.day])
        assert len(grouped) == len(df)

        grouped = df.groupby([lambda x: x.year, lambda x: x.month])
        expected = len({(x.year, x.month) for x in df.index})
        assert len(grouped) == expected

        # issue 11016
        df = pd.DataFrame(dict(a=[np.nan] * 3, b=[1, 2, 3]))
        assert len(df.groupby(('a'))) == 0
        assert len(df.groupby(('b'))) == 3
        assert len(df.groupby(['a', 'b'])) == 3

    def test_basic_regression(self):
        # regression
        T = [1.0 * x for x in lrange(1, 10) * 10][:1095]
        result = Series(T, lrange(0, len(T)))

        groupings = np.random.random((1100, ))
        groupings = Series(groupings, lrange(0, len(groupings))) * 10.

        grouped = result.groupby(groupings)
        grouped.mean()

    def test_with_na_groups(self):
        index = Index(np.arange(10))

        for dtype in ['float64', 'float32', 'int64', 'int32', 'int16', 'int8']:
            values = Series(np.ones(10), index, dtype=dtype)
            labels = Series([np.nan, 'foo', 'bar', 'bar', np.nan, np.nan,
                             'bar', 'bar', np.nan, 'foo'], index=index)

            # this SHOULD be an int
            grouped = values.groupby(labels)
            agged = grouped.agg(len)
            expected = Series([4, 2], index=['bar', 'foo'])

            assert_series_equal(agged, expected, check_dtype=False)

            # assert issubclass(agged.dtype.type, np.integer)

            # explicity return a float from my function
            def f(x):
                return float(len(x))

            agged = grouped.agg(f)
            expected = Series([4, 2], index=['bar', 'foo'])

            assert_series_equal(agged, expected, check_dtype=False)
            assert issubclass(agged.dtype.type, np.dtype(dtype).type)

    def test_indices_concatenation_order(self):

        # GH 2808

        def f1(x):
            y = x[(x.b % 2) == 1] ** 2
            if y.empty:
                multiindex = MultiIndex(levels=[[]] * 2, labels=[[]] * 2,
                                        names=['b', 'c'])
                res = DataFrame(None, columns=['a'], index=multiindex)
                return res
            else:
                y = y.set_index(['b', 'c'])
                return y

        def f2(x):
            y = x[(x.b % 2) == 1] ** 2
            if y.empty:
                return DataFrame()
            else:
                y = y.set_index(['b', 'c'])
                return y

        def f3(x):
            y = x[(x.b % 2) == 1] ** 2
            if y.empty:
                multiindex = MultiIndex(levels=[[]] * 2, labels=[[]] * 2,
                                        names=['foo', 'bar'])
                res = DataFrame(None, columns=['a', 'b'], index=multiindex)
                return res
            else:
                return y

        df = DataFrame({'a': [1, 2, 2, 2], 'b': lrange(4), 'c': lrange(5, 9)})

        df2 = DataFrame({'a': [3, 2, 2, 2], 'b': lrange(4), 'c': lrange(5, 9)})

        # correct result
        result1 = df.groupby('a').apply(f1)
        result2 = df2.groupby('a').apply(f1)
        assert_frame_equal(result1, result2)

        # should fail (not the same number of levels)
        pytest.raises(AssertionError, df.groupby('a').apply, f2)
        pytest.raises(AssertionError, df2.groupby('a').apply, f2)

        # should fail (incorrect shape)
        pytest.raises(AssertionError, df.groupby('a').apply, f3)
        pytest.raises(AssertionError, df2.groupby('a').apply, f3)

    def test_attr_wrapper(self):
        grouped = self.ts.groupby(lambda x: x.weekday())

        result = grouped.std()
        expected = grouped.agg(lambda x: np.std(x, ddof=1))
        assert_series_equal(result, expected)

        # this is pretty cool
        result = grouped.describe()
        expected = {}
        for name, gp in grouped:
            expected[name] = gp.describe()
        expected = DataFrame(expected).T
        assert_frame_equal(result, expected)

        # get attribute
        result = grouped.dtype
        expected = grouped.agg(lambda x: x.dtype)

        # make sure raises error
        pytest.raises(AttributeError, getattr, grouped, 'foo')

    def test_frame_groupby(self):
        grouped = self.tsframe.groupby(lambda x: x.weekday())

        # aggregate
        aggregated = grouped.aggregate(np.mean)
        assert len(aggregated) == 5
        assert len(aggregated.columns) == 4

        # by string
        tscopy = self.tsframe.copy()
        tscopy['weekday'] = [x.weekday() for x in tscopy.index]
        stragged = tscopy.groupby('weekday').aggregate(np.mean)
        assert_frame_equal(stragged, aggregated, check_names=False)

        # transform
        grouped = self.tsframe.head(30).groupby(lambda x: x.weekday())
        transformed = grouped.transform(lambda x: x - x.mean())
        assert len(transformed) == 30
        assert len(transformed.columns) == 4

        # transform propagate
        transformed = grouped.transform(lambda x: x.mean())
        for name, group in grouped:
            mean = group.mean()
            for idx in group.index:
                tm.assert_series_equal(transformed.xs(idx), mean,
                                       check_names=False)

        # iterate
        for weekday, group in grouped:
            assert group.index[0].weekday() == weekday

        # groups / group_indices
        groups = grouped.groups
        indices = grouped.indices

        for k, v in compat.iteritems(groups):
            samething = self.tsframe.index.take(indices[k])
            assert (samething == v).all()

    def test_frame_groupby_columns(self):
        mapping = {'A': 0, 'B': 0, 'C': 1, 'D': 1}
        grouped = self.tsframe.groupby(mapping, axis=1)

        # aggregate
        aggregated = grouped.aggregate(np.mean)
        assert len(aggregated) == len(self.tsframe)
        assert len(aggregated.columns) == 2

        # transform
        tf = lambda x: x - x.mean()
        groupedT = self.tsframe.T.groupby(mapping, axis=0)
        assert_frame_equal(groupedT.transform(tf).T, grouped.transform(tf))

        # iterate
        for k, v in grouped:
            assert len(v.columns) == 2

    def test_frame_set_name_single(self):
        grouped = self.df.groupby('A')

        result = grouped.mean()
        assert result.index.name == 'A'

        result = self.df.groupby('A', as_index=False).mean()
        assert result.index.name != 'A'

        result = grouped.agg(np.mean)
        assert result.index.name == 'A'

        result = grouped.agg({'C': np.mean, 'D': np.std})
        assert result.index.name == 'A'

        result = grouped['C'].mean()
        assert result.index.name == 'A'
        result = grouped['C'].agg(np.mean)
        assert result.index.name == 'A'
        result = grouped['C'].agg([np.mean, np.std])
        assert result.index.name == 'A'

        with tm.assert_produces_warning(FutureWarning,
                                        check_stacklevel=False):
            result = grouped['C'].agg({'foo': np.mean, 'bar': np.std})
        assert result.index.name == 'A'

    def test_multi_func(self):
        col1 = self.df['A']
        col2 = self.df['B']

        grouped = self.df.groupby([col1.get, col2.get])
        agged = grouped.mean()
        expected = self.df.groupby(['A', 'B']).mean()

        # TODO groupby get drops names
        assert_frame_equal(agged.loc[:, ['C', 'D']],
                           expected.loc[:, ['C', 'D']],
                           check_names=False)

        # some "groups" with no data
        df = DataFrame({'v1': np.random.randn(6),
                        'v2': np.random.randn(6),
                        'k1': np.array(['b', 'b', 'b', 'a', 'a', 'a']),
                        'k2': np.array(['1', '1', '1', '2', '2', '2'])},
                       index=['one', 'two', 'three', 'four', 'five', 'six'])
        # only verify that it works for now
        grouped = df.groupby(['k1', 'k2'])
        grouped.agg(np.sum)

    def test_multi_key_multiple_functions(self):
        grouped = self.df.groupby(['A', 'B'])['C']

        agged = grouped.agg([np.mean, np.std])
        expected = DataFrame({'mean': grouped.agg(np.mean),
                              'std': grouped.agg(np.std)})
        assert_frame_equal(agged, expected)

    def test_frame_multi_key_function_list(self):
        data = DataFrame(
            {'A': ['foo', 'foo', 'foo', 'foo', 'bar', 'bar', 'bar', 'bar',
                   'foo', 'foo', 'foo'],
             'B': ['one', 'one', 'one', 'two', 'one', 'one', 'one', 'two',
                   'two', 'two', 'one'],
             'C': ['dull', 'dull', 'shiny', 'dull', 'dull', 'shiny', 'shiny',
                   'dull', 'shiny', 'shiny', 'shiny'],
             'D': np.random.randn(11),
             'E': np.random.randn(11),
             'F': np.random.randn(11)})

        grouped = data.groupby(['A', 'B'])
        funcs = [np.mean, np.std]
        agged = grouped.agg(funcs)
        expected = concat([grouped['D'].agg(funcs), grouped['E'].agg(funcs),
                           grouped['F'].agg(funcs)],
                          keys=['D', 'E', 'F'], axis=1)
        assert (isinstance(agged.index, MultiIndex))
        assert (isinstance(expected.index, MultiIndex))
        assert_frame_equal(agged, expected)

    def test_groupby_multiple_columns(self):
        data = self.df
        grouped = data.groupby(['A', 'B'])

        def _check_op(op):

            with catch_warnings(record=True):
                result1 = op(grouped)

                expected = defaultdict(dict)
                for n1, gp1 in data.groupby('A'):
                    for n2, gp2 in gp1.groupby('B'):
                        expected[n1][n2] = op(gp2.loc[:, ['C', 'D']])
                expected = dict((k, DataFrame(v))
                                for k, v in compat.iteritems(expected))
                expected = Panel.fromDict(expected).swapaxes(0, 1)
                expected.major_axis.name, expected.minor_axis.name = 'A', 'B'

                # a little bit crude
                for col in ['C', 'D']:
                    result_col = op(grouped[col])
                    exp = expected[col]
                    pivoted = result1[col].unstack()
                    pivoted2 = result_col.unstack()
                    assert_frame_equal(pivoted.reindex_like(exp), exp)
                    assert_frame_equal(pivoted2.reindex_like(exp), exp)

        _check_op(lambda x: x.sum())
        _check_op(lambda x: x.mean())

        # test single series works the same
        result = data['C'].groupby([data['A'], data['B']]).mean()
        expected = data.groupby(['A', 'B']).mean()['C']

        assert_series_equal(result, expected)

    def test_groupby_as_index_agg(self):
        grouped = self.df.groupby('A', as_index=False)

        # single-key

        result = grouped.agg(np.mean)
        expected = grouped.mean()
        assert_frame_equal(result, expected)

        result2 = grouped.agg(OrderedDict([['C', np.mean], ['D', np.sum]]))
        expected2 = grouped.mean()
        expected2['D'] = grouped.sum()['D']
        assert_frame_equal(result2, expected2)

        grouped = self.df.groupby('A', as_index=True)
        expected3 = grouped['C'].sum()
        expected3 = DataFrame(expected3).rename(columns={'C': 'Q'})

        with tm.assert_produces_warning(FutureWarning,
                                        check_stacklevel=False):
            result3 = grouped['C'].agg({'Q': np.sum})
        assert_frame_equal(result3, expected3)

        # multi-key

        grouped = self.df.groupby(['A', 'B'], as_index=False)

        result = grouped.agg(np.mean)
        expected = grouped.mean()
        assert_frame_equal(result, expected)

        result2 = grouped.agg(OrderedDict([['C', np.mean], ['D', np.sum]]))
        expected2 = grouped.mean()
        expected2['D'] = grouped.sum()['D']
        assert_frame_equal(result2, expected2)

        expected3 = grouped['C'].sum()
        expected3 = DataFrame(expected3).rename(columns={'C': 'Q'})
        result3 = grouped['C'].agg({'Q': np.sum})
        assert_frame_equal(result3, expected3)

        # GH7115 & GH8112 & GH8582
        df = DataFrame(np.random.randint(0, 100, (50, 3)),
                       columns=['jim', 'joe', 'jolie'])
        ts = Series(np.random.randint(5, 10, 50), name='jim')

        gr = df.groupby(ts)
        gr.nth(0)  # invokes set_selection_from_grouper internally
        assert_frame_equal(gr.apply(sum), df.groupby(ts).apply(sum))

        for attr in ['mean', 'max', 'count', 'idxmax', 'cumsum', 'all']:
            gr = df.groupby(ts, as_index=False)
            left = getattr(gr, attr)()

            gr = df.groupby(ts.values, as_index=True)
            right = getattr(gr, attr)().reset_index(drop=True)

            assert_frame_equal(left, right)

    def test_as_index_series_return_frame(self):
        grouped = self.df.groupby('A', as_index=False)
        grouped2 = self.df.groupby(['A', 'B'], as_index=False)

        result = grouped['C'].agg(np.sum)
        expected = grouped.agg(np.sum).loc[:, ['A', 'C']]
        assert isinstance(result, DataFrame)
        assert_frame_equal(result, expected)

        result2 = grouped2['C'].agg(np.sum)
        expected2 = grouped2.agg(np.sum).loc[:, ['A', 'B', 'C']]
        assert isinstance(result2, DataFrame)
        assert_frame_equal(result2, expected2)

        result = grouped['C'].sum()
        expected = grouped.sum().loc[:, ['A', 'C']]
        assert isinstance(result, DataFrame)
        assert_frame_equal(result, expected)

        result2 = grouped2['C'].sum()
        expected2 = grouped2.sum().loc[:, ['A', 'B', 'C']]
        assert isinstance(result2, DataFrame)
        assert_frame_equal(result2, expected2)

        # corner case
        pytest.raises(Exception, grouped['C'].__getitem__, 'D')

    def test_groupby_as_index_cython(self):
        data = self.df

        # single-key
        grouped = data.groupby('A', as_index=False)
        result = grouped.mean()
        expected = data.groupby(['A']).mean()
        expected.insert(0, 'A', expected.index)
        expected.index = np.arange(len(expected))
        assert_frame_equal(result, expected)

        # multi-key
        grouped = data.groupby(['A', 'B'], as_index=False)
        result = grouped.mean()
        expected = data.groupby(['A', 'B']).mean()

        arrays = lzip(*expected.index.values)
        expected.insert(0, 'A', arrays[0])
        expected.insert(1, 'B', arrays[1])
        expected.index = np.arange(len(expected))
        assert_frame_equal(result, expected)

    def test_groupby_as_index_series_scalar(self):
        grouped = self.df.groupby(['A', 'B'], as_index=False)

        # GH #421

        result = grouped['C'].agg(len)
        expected = grouped.agg(len).loc[:, ['A', 'B', 'C']]
        assert_frame_equal(result, expected)

    def test_groupby_as_index_corner(self):
        pytest.raises(TypeError, self.ts.groupby, lambda x: x.weekday(),
                      as_index=False)

        pytest.raises(ValueError, self.df.groupby, lambda x: x.lower(),
                      as_index=False, axis=1)

    def test_groupby_as_index_apply(self):
        # GH #4648 and #3417
        df = DataFrame({'item_id': ['b', 'b', 'a', 'c', 'a', 'b'],
                        'user_id': [1, 2, 1, 1, 3, 1],
                        'time': range(6)})

        g_as = df.groupby('user_id', as_index=True)
        g_not_as = df.groupby('user_id', as_index=False)

        res_as = g_as.head(2).index
        res_not_as = g_not_as.head(2).index
        exp = Index([0, 1, 2, 4])
        assert_index_equal(res_as, exp)
        assert_index_equal(res_not_as, exp)

        res_as_apply = g_as.apply(lambda x: x.head(2)).index
        res_not_as_apply = g_not_as.apply(lambda x: x.head(2)).index

        # apply doesn't maintain the original ordering
        # changed in GH5610 as the as_index=False returns a MI here
        exp_not_as_apply = MultiIndex.from_tuples([(0, 0), (0, 2), (1, 1), (
            2, 4)])
        tp = [(1, 0), (1, 2), (2, 1), (3, 4)]
        exp_as_apply = MultiIndex.from_tuples(tp, names=['user_id', None])

        assert_index_equal(res_as_apply, exp_as_apply)
        assert_index_equal(res_not_as_apply, exp_not_as_apply)

        ind = Index(list('abcde'))
        df = DataFrame([[1, 2], [2, 3], [1, 4], [1, 5], [2, 6]], index=ind)
        res = df.groupby(0, as_index=False).apply(lambda x: x).index
        assert_index_equal(res, ind)

    def test_groupby_multiple_key(self):
        df = tm.makeTimeDataFrame()
        grouped = df.groupby([lambda x: x.year, lambda x: x.month,
                              lambda x: x.day])
        agged = grouped.sum()
        assert_almost_equal(df.values, agged.values)

        grouped = df.T.groupby([lambda x: x.year,
                                lambda x: x.month,
                                lambda x: x.day], axis=1)

        agged = grouped.agg(lambda x: x.sum())
        tm.assert_index_equal(agged.index, df.columns)
        assert_almost_equal(df.T.values, agged.values)

        agged = grouped.agg(lambda x: x.sum())
        assert_almost_equal(df.T.values, agged.values)

    def test_groupby_multi_corner(self):
        # test that having an all-NA column doesn't mess you up
        df = self.df.copy()
        df['bad'] = np.nan
        agged = df.groupby(['A', 'B']).mean()

        expected = self.df.groupby(['A', 'B']).mean()
        expected['bad'] = np.nan

        assert_frame_equal(agged, expected)

    def test_omit_nuisance(self):
        grouped = self.df.groupby('A')

        result = grouped.mean()
        expected = self.df.loc[:, ['A', 'C', 'D']].groupby('A').mean()
        assert_frame_equal(result, expected)

        agged = grouped.agg(np.mean)
        exp = grouped.mean()
        assert_frame_equal(agged, exp)

        df = self.df.loc[:, ['A', 'C', 'D']]
        df['E'] = datetime.now()
        grouped = df.groupby('A')
        result = grouped.agg(np.sum)
        expected = grouped.sum()
        assert_frame_equal(result, expected)

        # won't work with axis = 1
        grouped = df.groupby({'A': 0, 'C': 0, 'D': 1, 'E': 1}, axis=1)
        result = pytest.raises(TypeError, grouped.agg,
                               lambda x: x.sum(0, numeric_only=False))

    def test_omit_nuisance_python_multiple(self):
        grouped = self.three_group.groupby(['A', 'B'])

        agged = grouped.agg(np.mean)
        exp = grouped.mean()
        assert_frame_equal(agged, exp)

    def test_empty_groups_corner(self):
        # handle empty groups
        df = DataFrame({'k1': np.array(['b', 'b', 'b', 'a', 'a', 'a']),
                        'k2': np.array(['1', '1', '1', '2', '2', '2']),
                        'k3': ['foo', 'bar'] * 3,
                        'v1': np.random.randn(6),
                        'v2': np.random.randn(6)})

        grouped = df.groupby(['k1', 'k2'])
        result = grouped.agg(np.mean)
        expected = grouped.mean()
        assert_frame_equal(result, expected)

        grouped = self.mframe[3:5].groupby(level=0)
        agged = grouped.apply(lambda x: x.mean())
        agged_A = grouped['A'].apply(np.mean)
        assert_series_equal(agged['A'], agged_A)
        assert agged.index.name == 'first'

    def test_apply_concat_preserve_names(self):
        grouped = self.three_group.groupby(['A', 'B'])

        def desc(group):
            result = group.describe()
            result.index.name = 'stat'
            return result

        def desc2(group):
            result = group.describe()
            result.index.name = 'stat'
            result = result[:len(group)]
            # weirdo
            return result

        def desc3(group):
            result = group.describe()

            # names are different
            result.index.name = 'stat_%d' % len(group)

            result = result[:len(group)]
            # weirdo
            return result

        result = grouped.apply(desc)
        assert result.index.names == ('A', 'B', 'stat')

        result2 = grouped.apply(desc2)
        assert result2.index.names == ('A', 'B', 'stat')

        result3 = grouped.apply(desc3)
        assert result3.index.names == ('A', 'B', None)

    def test_nonsense_func(self):
        df = DataFrame([0])
        pytest.raises(Exception, df.groupby, lambda x: x + 'foo')

    def test_builtins_apply(self):  # GH8155
        df = pd.DataFrame(np.random.randint(1, 50, (1000, 2)),
                          columns=['jim', 'joe'])
        df['jolie'] = np.random.randn(1000)

        for keys in ['jim', ['jim', 'joe']]:  # single key & multi-key
            if keys == 'jim':
                continue
            for f in [max, min, sum]:
                fname = f.__name__
                result = df.groupby(keys).apply(f)
                result.shape
                ngroups = len(df.drop_duplicates(subset=keys))
                assert result.shape == (ngroups, 3), 'invalid frame shape: '\
                    '{} (expected ({}, 3))'.format(result.shape, ngroups)

                assert_frame_equal(result,  # numpy's equivalent function
                                   df.groupby(keys).apply(getattr(np, fname)))

                if f != sum:
                    expected = df.groupby(keys).agg(fname).reset_index()
                    expected.set_index(keys, inplace=True, drop=False)
                    assert_frame_equal(result, expected, check_dtype=False)

                assert_series_equal(getattr(result, fname)(),
                                    getattr(df, fname)())

    def test_max_min_non_numeric(self):
        # #2700
        aa = DataFrame({'nn': [11, 11, 22, 22],
                        'ii': [1, 2, 3, 4],
                        'ss': 4 * ['mama']})

        result = aa.groupby('nn').max()
        assert 'ss' in result

        result = aa.groupby('nn').max(numeric_only=False)
        assert 'ss' in result

        result = aa.groupby('nn').min()
        assert 'ss' in result

        result = aa.groupby('nn').min(numeric_only=False)
        assert 'ss' in result

    def test_arg_passthru(self):
        # make sure that we are passing thru kwargs
        # to our agg functions

        # GH3668
        # GH5724
        df = pd.DataFrame(
            {'group': [1, 1, 2],
             'int': [1, 2, 3],
             'float': [4., 5., 6.],
             'string': list('abc'),
             'category_string': pd.Series(list('abc')).astype('category'),
             'category_int': [7, 8, 9],
             'datetime': pd.date_range('20130101', periods=3),
             'datetimetz': pd.date_range('20130101',
                                         periods=3,
                                         tz='US/Eastern'),
             'timedelta': pd.timedelta_range('1 s', periods=3, freq='s')},
            columns=['group', 'int', 'float', 'string',
                     'category_string', 'category_int',
                     'datetime', 'datetimetz',
                     'timedelta'])

        expected_columns_numeric = Index(['int', 'float', 'category_int'])

        # mean / median
        expected = pd.DataFrame(
            {'category_int': [7.5, 9],
             'float': [4.5, 6.],
             'timedelta': [pd.Timedelta('1.5s'),
                           pd.Timedelta('3s')],
             'int': [1.5, 3],
             'datetime': [pd.Timestamp('2013-01-01 12:00:00'),
                          pd.Timestamp('2013-01-03 00:00:00')],
             'datetimetz': [
                 pd.Timestamp('2013-01-01 12:00:00', tz='US/Eastern'),
                 pd.Timestamp('2013-01-03 00:00:00', tz='US/Eastern')]},
            index=Index([1, 2], name='group'),
            columns=['int', 'float', 'category_int',
                     'datetime', 'datetimetz', 'timedelta'])
        for attr in ['mean', 'median']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns_numeric)

            result = f(numeric_only=False)
            assert_frame_equal(result.reindex_like(expected), expected)

        # TODO: min, max *should* handle
        # categorical (ordered) dtype
        expected_columns = Index(['int', 'float', 'string',
                                  'category_int',
                                  'datetime', 'datetimetz',
                                  'timedelta'])
        for attr in ['min', 'max']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

        expected_columns = Index(['int', 'float', 'string',
                                  'category_string', 'category_int',
                                  'datetime', 'datetimetz',
                                  'timedelta'])
        for attr in ['first', 'last']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

        expected_columns = Index(['int', 'float', 'string',
                                  'category_int', 'timedelta'])
        for attr in ['sum']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns_numeric)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

        expected_columns = Index(['int', 'float', 'category_int'])
        for attr in ['prod', 'cumprod']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns_numeric)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

        # like min, max, but don't include strings
        expected_columns = Index(['int', 'float',
                                  'category_int',
                                  'datetime', 'datetimetz',
                                  'timedelta'])
        for attr in ['cummin', 'cummax']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            # GH 15561: numeric_only=False set by default like min/max
            tm.assert_index_equal(result.columns, expected_columns)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

        expected_columns = Index(['int', 'float', 'category_int',
                                  'timedelta'])
        for attr in ['cumsum']:
            f = getattr(df.groupby('group'), attr)
            result = f()
            tm.assert_index_equal(result.columns, expected_columns_numeric)

            result = f(numeric_only=False)
            tm.assert_index_equal(result.columns, expected_columns)

    def test_wrap_aggregated_output_multindex(self):
        df = self.mframe.T
        df['baz', 'two'] = 'peekaboo'

        keys = [np.array([0, 0, 1]), np.array([0, 0, 1])]
        agged = df.groupby(keys).agg(np.mean)
        assert isinstance(agged.columns, MultiIndex)

        def aggfun(ser):
            if ser.name == ('foo', 'one'):
                raise TypeError
            else:
                return ser.sum()

        agged2 = df.groupby(keys).aggregate(aggfun)
        assert len(agged2.columns) + 1 == len(df.columns)

    def test_groupby_level_apply(self):
        frame = self.mframe

        result = frame.groupby(level=0).count()
        assert result.index.name == 'first'
        result = frame.groupby(level=1).count()
        assert result.index.name == 'second'

        result = frame['A'].groupby(level=0).count()
        assert result.index.name == 'first'

    def test_groupby_level_mapper(self):
        frame = self.mframe
        deleveled = frame.reset_index()

        mapper0 = {'foo': 0, 'bar': 0, 'baz': 1, 'qux': 1}
        mapper1 = {'one': 0, 'two': 0, 'three': 1}

        result0 = frame.groupby(mapper0, level=0).sum()
        result1 = frame.groupby(mapper1, level=1).sum()

        mapped_level0 = np.array([mapper0.get(x) for x in deleveled['first']])
        mapped_level1 = np.array([mapper1.get(x) for x in deleveled['second']])
        expected0 = frame.groupby(mapped_level0).sum()
        expected1 = frame.groupby(mapped_level1).sum()
        expected0.index.name, expected1.index.name = 'first', 'second'

        assert_frame_equal(result0, expected0)
        assert_frame_equal(result1, expected1)

    def test_groupby_level_nonmulti(self):
        # GH 1313, GH 13901
        s = Series([1, 2, 3, 10, 4, 5, 20, 6],
                   Index([1, 2, 3, 1, 4, 5, 2, 6], name='foo'))
        expected = Series([11, 22, 3, 4, 5, 6],
                          Index(range(1, 7), name='foo'))

        result = s.groupby(level=0).sum()
        tm.assert_series_equal(result, expected)
        result = s.groupby(level=[0]).sum()
        tm.assert_series_equal(result, expected)
        result = s.groupby(level=-1).sum()
        tm.assert_series_equal(result, expected)
        result = s.groupby(level=[-1]).sum()
        tm.assert_series_equal(result, expected)

        pytest.raises(ValueError, s.groupby, level=1)
        pytest.raises(ValueError, s.groupby, level=-2)
        pytest.raises(ValueError, s.groupby, level=[])
        pytest.raises(ValueError, s.groupby, level=[0, 0])
        pytest.raises(ValueError, s.groupby, level=[0, 1])
        pytest.raises(ValueError, s.groupby, level=[1])

    def test_groupby_complex(self):
        # GH 12902
        a = Series(data=np.arange(4) * (1 + 2j), index=[0, 0, 1, 1])
        expected = Series((1 + 2j, 5 + 10j))

        result = a.groupby(level=0).sum()
        assert_series_equal(result, expected)

        result = a.sum(level=0)
        assert_series_equal(result, expected)

    def test_apply_series_to_frame(self):
        def f(piece):
            with np.errstate(invalid='ignore'):
                logged = np.log(piece)
            return DataFrame({'value': piece,
                              'demeaned': piece - piece.mean(),
                              'logged': logged})

        dr = bdate_range('1/1/2000', periods=100)
        ts = Series(np.random.randn(100), index=dr)

        grouped = ts.groupby(lambda x: x.month)
        result = grouped.apply(f)

        assert isinstance(result, DataFrame)
        tm.assert_index_equal(result.index, ts.index)

    def test_apply_series_yield_constant(self):
        result = self.df.groupby(['A', 'B'])['C'].apply(len)
        assert result.index.names[:2] == ('A', 'B')

    def test_apply_frame_yield_constant(self):
        # GH13568
        result = self.df.groupby(['A', 'B']).apply(len)
        assert isinstance(result, Series)
        assert result.name is None

        result = self.df.groupby(['A', 'B'])[['C', 'D']].apply(len)
        assert isinstance(result, Series)
        assert result.name is None

    def test_apply_frame_to_series(self):
        grouped = self.df.groupby(['A', 'B'])
        result = grouped.apply(len)
        expected = grouped.count()['C']
        tm.assert_index_equal(result.index, expected.index)
        tm.assert_numpy_array_equal(result.values, expected.values)

    def test_apply_frame_concat_series(self):
        def trans(group):
            return group.groupby('B')['C'].sum().sort_values()[:2]

        def trans2(group):
            grouped = group.groupby(df.reindex(group.index)['B'])
            return grouped.sum().sort_values()[:2]

        df = DataFrame({'A': np.random.randint(0, 5, 1000),
                        'B': np.random.randint(0, 5, 1000),
                        'C': np.random.randn(1000)})

        result = df.groupby('A').apply(trans)
        exp = df.groupby('A')['C'].apply(trans2)
        assert_series_equal(result, exp, check_names=False)
        assert result.name == 'C'

    def test_apply_transform(self):
        grouped = self.ts.groupby(lambda x: x.month)
        result = grouped.apply(lambda x: x * 2)
        expected = grouped.transform(lambda x: x * 2)
        assert_series_equal(result, expected)

    def test_apply_multikey_corner(self):
        grouped = self.tsframe.groupby([lambda x: x.year, lambda x: x.month])

        def f(group):
            return group.sort_values('A')[-5:]

        result = grouped.apply(f)
        for key, group in grouped:
            assert_frame_equal(result.loc[key], f(group))

    def test_mutate_groups(self):

        # GH3380

        mydf = DataFrame({
            'cat1': ['a'] * 8 + ['b'] * 6,
            'cat2': ['c'] * 2 + ['d'] * 2 + ['e'] * 2 + ['f'] * 2 + ['c'] * 2 +
            ['d'] * 2 + ['e'] * 2,
            'cat3': lmap(lambda x: 'g%s' % x, lrange(1, 15)),
            'val': np.random.randint(100, size=14),
        })

        def f_copy(x):
            x = x.copy()
            x['rank'] = x.val.rank(method='min')
            return x.groupby('cat2')['rank'].min()

        def f_no_copy(x):
            x['rank'] = x.val.rank(method='min')
            return x.groupby('cat2')['rank'].min()

        grpby_copy = mydf.groupby('cat1').apply(f_copy)
        grpby_no_copy = mydf.groupby('cat1').apply(f_no_copy)
        assert_series_equal(grpby_copy, grpby_no_copy)

    def test_no_mutate_but_looks_like(self):

        # GH 8467
        # first show's mutation indicator
        # second does not, but should yield the same results
        df = DataFrame({'key': [1, 1, 1, 2, 2, 2, 3, 3, 3], 'value': range(9)})

        result1 = df.groupby('key', group_keys=True).apply(lambda x: x[:].key)
        result2 = df.groupby('key', group_keys=True).apply(lambda x: x.key)
        assert_series_equal(result1, result2)

    def test_apply_chunk_view(self):
        # Low level tinkering could be unsafe, make sure not
        df = DataFrame({'key': [1, 1, 1, 2, 2, 2, 3, 3, 3],
                        'value': lrange(9)})

        # return view
        f = lambda x: x[:2]

        result = df.groupby('key', group_keys=False).apply(f)
        expected = df.take([0, 1, 3, 4, 6, 7])
        assert_frame_equal(result, expected)

    def test_apply_no_name_column_conflict(self):
        df = DataFrame({'name': [1, 1, 1, 1, 1, 1, 2, 2, 2, 2],
                        'name2': [0, 0, 0, 1, 1, 1, 0, 0, 1, 1],
                        'value': lrange(10)[::-1]})

        # it works! #2605
        grouped = df.groupby(['name', 'name2'])
        grouped.apply(lambda x: x.sort_values('value', inplace=True))

    def test_groupby_series_indexed_differently(self):
        s1 = Series([5.0, -9.0, 4.0, 100., -5., 55., 6.7],
                    index=Index(['a', 'b', 'c', 'd', 'e', 'f', 'g']))
        s2 = Series([1.0, 1.0, 4.0, 5.0, 5.0, 7.0],
                    index=Index(['a', 'b', 'd', 'f', 'g', 'h']))

        grouped = s1.groupby(s2)
        agged = grouped.mean()
        exp = s1.groupby(s2.reindex(s1.index).get).mean()
        assert_series_equal(agged, exp)

    def test_groupby_with_hier_columns(self):
        tuples = list(zip(*[['bar', 'bar', 'baz', 'baz', 'foo', 'foo', 'qux',
                             'qux'], ['one', 'two', 'one', 'two', 'one', 'two',
                                      'one', 'two']]))
        index = MultiIndex.from_tuples(tuples)
        columns = MultiIndex.from_tuples([('A', 'cat'), ('B', 'dog'), (
            'B', 'cat'), ('A', 'dog')])
        df = DataFrame(np.random.randn(8, 4), index=index, columns=columns)

        result = df.groupby(level=0).mean()
        tm.assert_index_equal(result.columns, columns)

        result = df.groupby(level=0, axis=1).mean()
        tm.assert_index_equal(result.index, df.index)

        result = df.groupby(level=0).agg(np.mean)
        tm.assert_index_equal(result.columns, columns)

        result = df.groupby(level=0).apply(lambda x: x.mean())
        tm.assert_index_equal(result.columns, columns)

        result = df.groupby(level=0, axis=1).agg(lambda x: x.mean(1))
        tm.assert_index_equal(result.columns, Index(['A', 'B']))
        tm.assert_index_equal(result.index, df.index)

        # add a nuisance column
        sorted_columns, _ = columns.sortlevel(0)
        df['A', 'foo'] = 'bar'
        result = df.groupby(level=0).mean()
        tm.assert_index_equal(result.columns, df.columns[:-1])

    def test_pass_args_kwargs(self):
        from numpy import percentile

        def f(x, q=None, axis=0):
            return percentile(x, q, axis=axis)

        g = lambda x: percentile(x, 80, axis=0)

        # Series
        ts_grouped = self.ts.groupby(lambda x: x.month)
        agg_result = ts_grouped.agg(percentile, 80, axis=0)
        apply_result = ts_grouped.apply(percentile, 80, axis=0)
        trans_result = ts_grouped.transform(percentile, 80, axis=0)

        agg_expected = ts_grouped.quantile(.8)
        trans_expected = ts_grouped.transform(g)

        assert_series_equal(apply_result, agg_expected)
        assert_series_equal(agg_result, agg_expected, check_names=False)
        assert_series_equal(trans_result, trans_expected)

        agg_result = ts_grouped.agg(f, q=80)
        apply_result = ts_grouped.apply(f, q=80)
        trans_result = ts_grouped.transform(f, q=80)
        assert_series_equal(agg_result, agg_expected)
        assert_series_equal(apply_result, agg_expected)
        assert_series_equal(trans_result, trans_expected)

        # DataFrame
        df_grouped = self.tsframe.groupby(lambda x: x.month)
        agg_result = df_grouped.agg(percentile, 80, axis=0)
        apply_result = df_grouped.apply(DataFrame.quantile, .8)
        expected = df_grouped.quantile(.8)
        assert_frame_equal(apply_result, expected)
        assert_frame_equal(agg_result, expected, check_names=False)

        agg_result = df_grouped.agg(f, q=80)
        apply_result = df_grouped.apply(DataFrame.quantile, q=.8)
        assert_frame_equal(agg_result, expected, check_names=False)
        assert_frame_equal(apply_result, expected)

    def test_non_cython_api(self):

        # GH5610
        # non-cython calls should not include the grouper

        df = DataFrame(
            [[1, 2, 'foo'],
             [1, np.nan, 'bar'],
             [3, np.nan, 'baz']],
            columns=['A', 'B', 'C'])
        g = df.groupby('A')
        gni = df.groupby('A', as_index=False)

        # mad
        expected = DataFrame([[0], [np.nan]], columns=['B'], index=[1, 3])
        expected.index.name = 'A'
        result = g.mad()
        assert_frame_equal(result, expected)

        expected = DataFrame([[0., 0.], [0, np.nan]], columns=['A', 'B'],
                             index=[0, 1])
        result = gni.mad()
        assert_frame_equal(result, expected)

        # describe
        expected_index = pd.Index([1, 3], name='A')
        expected_col = pd.MultiIndex(levels=[['B'],
                                             ['count', 'mean', 'std', 'min',
                                              '25%', '50%', '75%', 'max']],
                                     labels=[[0] * 8, list(range(8))])
        expected = pd.DataFrame([[1.0, 2.0, np.nan, 2.0, 2.0, 2.0, 2.0, 2.0],
                                 [0.0, np.nan, np.nan, np.nan, np.nan, np.nan,
                                  np.nan, np.nan]],
                                index=expected_index,
                                columns=expected_col)
        result = g.describe()
        assert_frame_equal(result, expected)

        expected = pd.concat([df[df.A == 1].describe().unstack().to_frame().T,
                              df[df.A == 3].describe().unstack().to_frame().T])
        expected.index = pd.Index([0, 1])
        result = gni.describe()
        assert_frame_equal(result, expected)

        # any
        expected = DataFrame([[True, True], [False, True]], columns=['B', 'C'],
                             index=[1, 3])
        expected.index.name = 'A'
        result = g.any()
        assert_frame_equal(result, expected)

        # idxmax
        expected = DataFrame([[0.0], [np.nan]], columns=['B'], index=[1, 3])
        expected.index.name = 'A'
        result = g.idxmax()
        assert_frame_equal(result, expected)

    def test_cython_api2(self):

        # this takes the fast apply path

        # cumsum (GH5614)
        df = DataFrame(
            [[1, 2, np.nan], [1, np.nan, 9], [3, 4, 9]
             ], columns=['A', 'B', 'C'])
        expected = DataFrame(
            [[2, np.nan], [np.nan, 9], [4, 9]], columns=['B', 'C'])
        result = df.groupby('A').cumsum()
        assert_frame_equal(result, expected)

        # GH 5755 - cumsum is a transformer and should ignore as_index
        result = df.groupby('A', as_index=False).cumsum()
        assert_frame_equal(result, expected)

        # GH 13994
        result = df.groupby('A').cumsum(axis=1)
        expected = df.cumsum(axis=1)
        assert_frame_equal(result, expected)
        result = df.groupby('A').cumprod(axis=1)
        expected = df.cumprod(axis=1)
        assert_frame_equal(result, expected)

    def test_grouping_ndarray(self):
        grouped = self.df.groupby(self.df['A'].values)

        result = grouped.sum()
        expected = self.df.groupby('A').sum()
        assert_frame_equal(result, expected, check_names=False
                           )  # Note: no names when grouping by value

    def test_apply_typecast_fail(self):
        df = DataFrame({'d': [1., 1., 1., 2., 2., 2.],
                        'c': np.tile(
                            ['a', 'b', 'c'], 2),
                        'v': np.arange(1., 7.)})

        def f(group):
            v = group['v']
            group['v2'] = (v - v.min()) / (v.max() - v.min())
            return group

        result = df.groupby('d').apply(f)

        expected = df.copy()
        expected['v2'] = np.tile([0., 0.5, 1], 2)

        assert_frame_equal(result, expected)

    def test_apply_multiindex_fail(self):
        index = MultiIndex.from_arrays([[0, 0, 0, 1, 1, 1], [1, 2, 3, 1, 2, 3]
                                        ])
        df = DataFrame({'d': [1., 1., 1., 2., 2., 2.],
                        'c': np.tile(['a', 'b', 'c'], 2),
                        'v': np.arange(1., 7.)}, index=index)

        def f(group):
            v = group['v']
            group['v2'] = (v - v.min()) / (v.max() - v.min())
            return group

        result = df.groupby('d').apply(f)

        expected = df.copy()
        expected['v2'] = np.tile([0., 0.5, 1], 2)

        assert_frame_equal(result, expected)

    def test_apply_corner(self):
        result = self.tsframe.groupby(lambda x: x.year).apply(lambda x: x * 2)
        expected = self.tsframe * 2
        assert_frame_equal(result, expected)

    def test_apply_without_copy(self):
        # GH 5545
        # returning a non-copy in an applied function fails

        data = DataFrame({'id_field': [100, 100, 200, 300],
                          'category': ['a', 'b', 'c', 'c'],
                          'value': [1, 2, 3, 4]})

        def filt1(x):
            if x.shape[0] == 1:
                return x.copy()
            else:
                return x[x.category == 'c']

        def filt2(x):
            if x.shape[0] == 1:
                return x
            else:
                return x[x.category == 'c']

        expected = data.groupby('id_field').apply(filt1)
        result = data.groupby('id_field').apply(filt2)
        assert_frame_equal(result, expected)

    def test_apply_corner_cases(self):
        # #535, can't use sliding iterator

        N = 1000
        labels = np.random.randint(0, 100, size=N)
        df = DataFrame({'key': labels,
                        'value1': np.random.randn(N),
                        'value2': ['foo', 'bar', 'baz', 'qux'] * (N // 4)})

        grouped = df.groupby('key')

        def f(g):
            g['value3'] = g['value1'] * 2
            return g

        result = grouped.apply(f)
        assert 'value3' in result

    def test_groupby_wrong_multi_labels(self):
        data = """index,foo,bar,baz,spam,data
0,foo1,bar1,baz1,spam2,20
1,foo1,bar2,baz1,spam3,30
2,foo2,bar2,baz1,spam2,40
3,foo1,bar1,baz2,spam1,50
4,foo3,bar1,baz2,spam1,60"""

        data = read_csv(StringIO(data), index_col=0)

        grouped = data.groupby(['foo', 'bar', 'baz', 'spam'])

        result = grouped.agg(np.mean)
        expected = grouped.mean()
        assert_frame_equal(result, expected)

    def test_groupby_series_with_name(self):
        result = self.df.groupby(self.df['A']).mean()
        result2 = self.df.groupby(self.df['A'], as_index=False).mean()
        assert result.index.name == 'A'
        assert 'A' in result2

        result = self.df.groupby([self.df['A'], self.df['B']]).mean()
        result2 = self.df.groupby([self.df['A'], self.df['B']],
                                  as_index=False).mean()
        assert result.index.names == ('A', 'B')
        assert 'A' in result2
        assert 'B' in result2

    def test_seriesgroupby_name_attr(self):
        # GH 6265
        result = self.df.groupby('A')['C']
        assert result.count().name == 'C'
        assert result.mean().name == 'C'

        testFunc = lambda x: np.sum(x) * 2
        assert result.agg(testFunc).name == 'C'

    def test_consistency_name(self):
        # GH 12363

        df = DataFrame({'A': ['foo', 'bar', 'foo', 'bar',
                              'foo', 'bar', 'foo', 'foo'],
                        'B': ['one', 'one', 'two', 'two',
                              'two', 'two', 'one', 'two'],
                        'C': np.random.randn(8) + 1.0,
                        'D': np.arange(8)})

        expected = df.groupby(['A']).B.count()
        result = df.B.groupby(df.A).count()
        assert_series_equal(result, expected)

    def test_groupby_name_propagation(self):
        # GH 6124
        def summarize(df, name=None):
            return Series({'count': 1, 'mean': 2, 'omissions': 3, }, name=name)

        def summarize_random_name(df):
            # Provide a different name for each Series.  In this case, groupby
            # should not attempt to propagate the Series name since they are
            # inconsistent.
            return Series({
                'count': 1,
                'mean': 2,
                'omissions': 3,
            }, name=df.iloc[0]['A'])

        metrics = self.df.groupby('A').apply(summarize)
        assert metrics.columns.name is None
        metrics = self.df.groupby('A').apply(summarize, 'metrics')
        assert metrics.columns.name == 'metrics'
        metrics = self.df.groupby('A').apply(summarize_random_name)
        assert metrics.columns.name is None

    def test_groupby_nonstring_columns(self):
        df = DataFrame([np.arange(10) for x in range(10)])
        grouped = df.groupby(0)
        result = grouped.mean()
        expected = df.groupby(df[0]).mean()
        assert_frame_equal(result, expected)

    def test_groupby_mixed_type_columns(self):
        # GH 13432, unorderable types in py3
        df = DataFrame([[0, 1, 2]], columns=['A', 'B', 0])
        expected = DataFrame([[1, 2]], columns=['B', 0],
                             index=Index([0], name='A'))

        result = df.groupby('A').first()
        tm.assert_frame_equal(result, expected)

        result = df.groupby('A').sum()
        tm.assert_frame_equal(result, expected)

    def test_cython_grouper_series_bug_noncontig(self):
        arr = np.empty((100, 100))
        arr.fill(np.nan)
        obj = Series(arr[:, 0], index=lrange(100))
        inds = np.tile(lrange(10), 10)

        result = obj.groupby(inds).agg(Series.median)
        assert result.isna().all()

    def test_series_grouper_noncontig_index(self):
        index = Index(tm.rands_array(10, 100))

        values = Series(np.random.randn(50), index=index[::2])
        labels = np.random.randint(0, 5, 50)

        # it works!
        grouped = values.groupby(labels)

        # accessing the index elements causes segfault
        f = lambda x: len(set(map(id, x.index)))
        grouped.agg(f)

    def test_convert_objects_leave_decimal_alone(self):

        from decimal import Decimal

        s = Series(lrange(5))
        labels = np.array(['a', 'b', 'c', 'd', 'e'], dtype='O')

        def convert_fast(x):
            return Decimal(str(x.mean()))

        def convert_force_pure(x):
            # base will be length 0
            assert (len(x.base) > 0)
            return Decimal(str(x.mean()))

        grouped = s.groupby(labels)

        result = grouped.agg(convert_fast)
        assert result.dtype == np.object_
        assert isinstance(result[0], Decimal)

        result = grouped.agg(convert_force_pure)
        assert result.dtype == np.object_
        assert isinstance(result[0], Decimal)

    def test_fast_apply(self):
        # make sure that fast apply is correctly called
        # rather than raising any kind of error
        # otherwise the python path will be callsed
        # which slows things down
        N = 1000
        labels = np.random.randint(0, 2000, size=N)
        labels2 = np.random.randint(0, 3, size=N)
        df = DataFrame({'key': labels,
                        'key2': labels2,
                        'value1': np.random.randn(N),
                        'value2': ['foo', 'bar', 'baz', 'qux'] * (N // 4)})

        def f(g):
            return 1

        g = df.groupby(['key', 'key2'])

        grouper = g.grouper

        splitter = grouper._get_splitter(g._selected_obj, axis=g.axis)
        group_keys = grouper._get_group_keys()

        values, mutated = splitter.fast_apply(f, group_keys)
        assert not mutated

    def test_apply_with_mixed_dtype(self):
        # GH3480, apply with mixed dtype on axis=1 breaks in 0.11
        df = DataFrame({'foo1': ['one', 'two', 'two', 'three', 'one', 'two'],
                        'foo2': np.random.randn(6)})
        result = df.apply(lambda x: x, axis=1)
        assert_series_equal(df.get_dtype_counts(), result.get_dtype_counts())

        # GH 3610 incorrect dtype conversion with as_index=False
        df = DataFrame({"c1": [1, 2, 6, 6, 8]})
        df["c2"] = df.c1 / 2.0
        result1 = df.groupby("c2").mean().reset_index().c2
        result2 = df.groupby("c2", as_index=False).mean().c2
        assert_series_equal(result1, result2)

    def test_groupby_aggregation_mixed_dtype(self):

        # GH 6212
        expected = DataFrame({
            'v1': [5, 5, 7, np.nan, 3, 3, 4, 1],
            'v2': [55, 55, 77, np.nan, 33, 33, 44, 11]},
            index=MultiIndex.from_tuples([(1, 95), (1, 99), (2, 95), (2, 99),
                                          ('big', 'damp'),
                                          ('blue', 'dry'),
                                          ('red', 'red'), ('red', 'wet')],
                                         names=['by1', 'by2']))

        df = DataFrame({
            'v1': [1, 3, 5, 7, 8, 3, 5, np.nan, 4, 5, 7, 9],
            'v2': [11, 33, 55, 77, 88, 33, 55, np.nan, 44, 55, 77, 99],
            'by1': ["red", "blue", 1, 2, np.nan, "big", 1, 2, "red", 1, np.nan,
                    12],
            'by2': ["wet", "dry", 99, 95, np.nan, "damp", 95, 99, "red", 99,
                    np.nan, np.nan]
        })

        g = df.groupby(['by1', 'by2'])
        result = g[['v1', 'v2']].mean()
        assert_frame_equal(result, expected)

    def test_groupby_dtype_inference_empty(self):
        # GH 6733
        df = DataFrame({'x': [], 'range': np.arange(0, dtype='int64')})
        assert df['x'].dtype == np.float64

        result = df.groupby('x').first()
        exp_index = Index([], name='x', dtype=np.float64)
        expected = DataFrame({'range': Series(
            [], index=exp_index, dtype='int64')})
        assert_frame_equal(result, expected, by_blocks=True)

    def test_groupby_list_infer_array_like(self):
        result = self.df.groupby(list(self.df['A'])).mean()
        expected = self.df.groupby(self.df['A']).mean()
        assert_frame_equal(result, expected, check_names=False)

        pytest.raises(Exception, self.df.groupby, list(self.df['A'][:-1]))

        # pathological case of ambiguity
        df = DataFrame({'foo': [0, 1],
                        'bar': [3, 4],
                        'val': np.random.randn(2)})

        result = df.groupby(['foo', 'bar']).mean()
        expected = df.groupby([df['foo'], df['bar']]).mean()[['val']]

    def test_groupby_keys_same_size_as_index(self):
        # GH 11185
        freq = 's'
        index = pd.date_range(start=pd.Timestamp('2015-09-29T11:34:44-0700'),
                              periods=2, freq=freq)
        df = pd.DataFrame([['A', 10], ['B', 15]], columns=[
            'metric', 'values'
        ], index=index)
        result = df.groupby([pd.Grouper(level=0, freq=freq), 'metric']).mean()
        expected = df.set_index([df.index, 'metric'])

        assert_frame_equal(result, expected)

    def test_groupby_one_row(self):
        # GH 11741
        df1 = pd.DataFrame(np.random.randn(1, 4), columns=list('ABCD'))
        pytest.raises(KeyError, df1.groupby, 'Z')
        df2 = pd.DataFrame(np.random.randn(2, 4), columns=list('ABCD'))
        pytest.raises(KeyError, df2.groupby, 'Z')

    def test_groupby_nat_exclude(self):
        # GH 6992
        df = pd.DataFrame(
            {'values': np.random.randn(8),
             'dt': [np.nan, pd.Timestamp('2013-01-01'), np.nan, pd.Timestamp(
                 '2013-02-01'), np.nan, pd.Timestamp('2013-02-01'), np.nan,
                pd.Timestamp('2013-01-01')],
             'str': [np.nan, 'a', np.nan, 'a', np.nan, 'a', np.nan, 'b']})
        grouped = df.groupby('dt')

        expected = [pd.Index([1, 7]), pd.Index([3, 5])]
        keys = sorted(grouped.groups.keys())
        assert len(keys) == 2
        for k, e in zip(keys, expected):
            # grouped.groups keys are np.datetime64 with system tz
            # not to be affected by tz, only compare values
            tm.assert_index_equal(grouped.groups[k], e)

        # confirm obj is not filtered
        tm.assert_frame_equal(grouped.grouper.groupings[0].obj, df)
        assert grouped.ngroups == 2

        expected = {
            Timestamp('2013-01-01 00:00:00'): np.array([1, 7], dtype=np.int64),
            Timestamp('2013-02-01 00:00:00'): np.array([3, 5], dtype=np.int64)
        }

        for k in grouped.indices:
            tm.assert_numpy_array_equal(grouped.indices[k], expected[k])

        tm.assert_frame_equal(
            grouped.get_group(Timestamp('2013-01-01')), df.iloc[[1, 7]])
        tm.assert_frame_equal(
            grouped.get_group(Timestamp('2013-02-01')), df.iloc[[3, 5]])

        pytest.raises(KeyError, grouped.get_group, pd.NaT)

        nan_df = DataFrame({'nan': [np.nan, np.nan, np.nan],
                            'nat': [pd.NaT, pd.NaT, pd.NaT]})
        assert nan_df['nan'].dtype == 'float64'
        assert nan_df['nat'].dtype == 'datetime64[ns]'

        for key in ['nan', 'nat']:
            grouped = nan_df.groupby(key)
            assert grouped.groups == {}
            assert grouped.ngroups == 0
            assert grouped.indices == {}
            pytest.raises(KeyError, grouped.get_group, np.nan)
            pytest.raises(KeyError, grouped.get_group, pd.NaT)

    def test_sparse_friendly(self):
        sdf = self.df[['C', 'D']].to_sparse()
        with catch_warnings(record=True):
            panel = tm.makePanel()
            tm.add_nans(panel)

        def _check_work(gp):
            gp.mean()
            gp.agg(np.mean)
            dict(iter(gp))

        # it works!
        _check_work(sdf.groupby(lambda x: x // 2))
        _check_work(sdf['C'].groupby(lambda x: x // 2))
        _check_work(sdf.groupby(self.df['A']))

        # do this someday
        # _check_work(panel.groupby(lambda x: x.month, axis=1))

    def test_panel_groupby(self):
        with catch_warnings(record=True):
            self.panel = tm.makePanel()
            tm.add_nans(self.panel)
            grouped = self.panel.groupby({'ItemA': 0, 'ItemB': 0, 'ItemC': 1},
                                         axis='items')
            agged = grouped.mean()
            agged2 = grouped.agg(lambda x: x.mean('items'))

            tm.assert_panel_equal(agged, agged2)

            tm.assert_index_equal(agged.items, Index([0, 1]))

            grouped = self.panel.groupby(lambda x: x.month, axis='major')
            agged = grouped.mean()

            exp = Index(sorted(list(set(self.panel.major_axis.month))))
            tm.assert_index_equal(agged.major_axis, exp)

            grouped = self.panel.groupby({'A': 0, 'B': 0, 'C': 1, 'D': 1},
                                         axis='minor')
            agged = grouped.mean()
            tm.assert_index_equal(agged.minor_axis, Index([0, 1]))

    def test_groupby_2d_malformed(self):
        d = DataFrame(index=lrange(2))
        d['group'] = ['g1', 'g2']
        d['zeros'] = [0, 0]
        d['ones'] = [1, 1]
        d['label'] = ['l1', 'l2']
        tmp = d.groupby(['group']).mean()
        res_values = np.array([[0, 1], [0, 1]], dtype=np.int64)
        tm.assert_index_equal(tmp.columns, Index(['zeros', 'ones']))
        tm.assert_numpy_array_equal(tmp.values, res_values)

    def test_int32_overflow(self):
        B = np.concatenate((np.arange(10000), np.arange(10000), np.arange(5000)
                            ))
        A = np.arange(25000)
        df = DataFrame({'A': A,
                        'B': B,
                        'C': A,
                        'D': B,
                        'E': np.random.randn(25000)})

        left = df.groupby(['A', 'B', 'C', 'D']).sum()
        right = df.groupby(['D', 'C', 'B', 'A']).sum()
        assert len(left) == len(right)

    def test_groupby_sort_multi(self):
        df = DataFrame({'a': ['foo', 'bar', 'baz'],
                        'b': [3, 2, 1],
                        'c': [0, 1, 2],
                        'd': np.random.randn(3)})

        tups = lmap(tuple, df[['a', 'b', 'c']].values)
        tups = com._asarray_tuplesafe(tups)
        result = df.groupby(['a', 'b', 'c'], sort=True).sum()
        tm.assert_numpy_array_equal(result.index.values, tups[[1, 2, 0]])

        tups = lmap(tuple, df[['c', 'a', 'b']].values)
        tups = com._asarray_tuplesafe(tups)
        result = df.groupby(['c', 'a', 'b'], sort=True).sum()
        tm.assert_numpy_array_equal(result.index.values, tups)

        tups = lmap(tuple, df[['b', 'c', 'a']].values)
        tups = com._asarray_tuplesafe(tups)
        result = df.groupby(['b', 'c', 'a'], sort=True).sum()
        tm.assert_numpy_array_equal(result.index.values, tups[[2, 1, 0]])

        df = DataFrame({'a': [0, 1, 2, 0, 1, 2],
                        'b': [0, 0, 0, 1, 1, 1],
                        'd': np.random.randn(6)})
        grouped = df.groupby(['a', 'b'])['d']
        result = grouped.sum()
        _check_groupby(df, result, ['a', 'b'], 'd')

    def test_intercept_builtin_sum(self):
        s = Series([1., 2., np.nan, 3.])
        grouped = s.groupby([0, 1, 2, 2])

        result = grouped.agg(builtins.sum)
        result2 = grouped.apply(builtins.sum)
        expected = grouped.sum()
        assert_series_equal(result, expected)
        assert_series_equal(result2, expected)

    def test_rank_apply(self):
        lev1 = tm.rands_array(10, 100)
        lev2 = tm.rands_array(10, 130)
        lab1 = np.random.randint(0, 100, size=500)
        lab2 = np.random.randint(0, 130, size=500)

        df = DataFrame({'value': np.random.randn(500),
                        'key1': lev1.take(lab1),
                        'key2': lev2.take(lab2)})

        result = df.groupby(['key1', 'key2']).value.rank()

        expected = []
        for key, piece in df.groupby(['key1', 'key2']):
            expected.append(piece.value.rank())
        expected = concat(expected, axis=0)
        expected = expected.reindex(result.index)
        assert_series_equal(result, expected)

        result = df.groupby(['key1', 'key2']).value.rank(pct=True)

        expected = []
        for key, piece in df.groupby(['key1', 'key2']):
            expected.append(piece.value.rank(pct=True))
        expected = concat(expected, axis=0)
        expected = expected.reindex(result.index)
        assert_series_equal(result, expected)

    def test_dont_clobber_name_column(self):
        df = DataFrame({'key': ['a', 'a', 'a', 'b', 'b', 'b'],
                        'name': ['foo', 'bar', 'baz'] * 2})

        result = df.groupby('key').apply(lambda x: x)
        assert_frame_equal(result, df)

    def test_skip_group_keys(self):
        from pandas import concat

        tsf = tm.makeTimeDataFrame()

        grouped = tsf.groupby(lambda x: x.month, group_keys=False)
        result = grouped.apply(lambda x: x.sort_values(by='A')[:3])

        pieces = []
        for key, group in grouped:
            pieces.append(group.sort_values(by='A')[:3])

        expected = concat(pieces)
        assert_frame_equal(result, expected)

        grouped = tsf['A'].groupby(lambda x: x.month, group_keys=False)
        result = grouped.apply(lambda x: x.sort_values()[:3])

        pieces = []
        for key, group in grouped:
            pieces.append(group.sort_values()[:3])

        expected = concat(pieces)
        assert_series_equal(result, expected)

    def test_no_nonsense_name(self):
        # GH #995
        s = self.frame['C'].copy()
        s.name = None

        result = s.groupby(self.frame['A']).agg(np.sum)
        assert result.name is None

    def test_multifunc_sum_bug(self):
        # GH #1065
        x = DataFrame(np.arange(9).reshape(3, 3))
        x['test'] = 0
        x['fl'] = [1.3, 1.5, 1.6]

        grouped = x.groupby('test')
        result = grouped.agg({'fl': 'sum', 2: 'size'})
        assert result['fl'].dtype == np.float64

    def test_handle_dict_return_value(self):
        def f(group):
            return {'min': group.min(), 'max': group.max()}

        def g(group):
            return Series({'min': group.min(), 'max': group.max()})

        result = self.df.groupby('A')['C'].apply(f)
        expected = self.df.groupby('A')['C'].apply(g)

        assert isinstance(result, Series)
        assert_series_equal(result, expected)

    def test_set_group_name(self):
        def f(group):
            assert group.name is not None
            return group

        def freduce(group):
            assert group.name is not None
            return group.sum()

        def foo(x):
            return freduce(x)

        def _check_all(grouped):
            # make sure all these work
            grouped.apply(f)
            grouped.aggregate(freduce)
            grouped.aggregate({'C': freduce, 'D': freduce})
            grouped.transform(f)

            grouped['C'].apply(f)
            grouped['C'].aggregate(freduce)
            grouped['C'].aggregate([freduce, foo])
            grouped['C'].transform(f)

        _check_all(self.df.groupby('A'))
        _check_all(self.df.groupby(['A', 'B']))

    def test_group_name_available_in_inference_pass(self):
        # gh-15062
        df = pd.DataFrame({'a': [0, 0, 1, 1, 2, 2], 'b': np.arange(6)})

        names = []

        def f(group):
            names.append(group.name)
            return group.copy()

        df.groupby('a', sort=False, group_keys=False).apply(f)
        # we expect 2 zeros because we call ``f`` once to see if a faster route
        # can be used.
        expected_names = [0, 0, 1, 2]
        assert names == expected_names

    def test_no_dummy_key_names(self):
        # see gh-1291
        result = self.df.groupby(self.df['A'].values).sum()
        assert result.index.name is None

        result = self.df.groupby([self.df['A'].values, self.df['B'].values
                                  ]).sum()
        assert result.index.names == (None, None)

    def test_groupby_sort_multiindex_series(self):
        # series multiindex groupby sort argument was not being passed through
        # _compress_group_index
        # GH 9444
        index = MultiIndex(levels=[[1, 2], [1, 2]],
                           labels=[[0, 0, 0, 0, 1, 1], [1, 1, 0, 0, 0, 0]],
                           names=['a', 'b'])
        mseries = Series([0, 1, 2, 3, 4, 5], index=index)
        index = MultiIndex(levels=[[1, 2], [1, 2]],
                           labels=[[0, 0, 1], [1, 0, 0]], names=['a', 'b'])
        mseries_result = Series([0, 2, 4], index=index)

        result = mseries.groupby(level=['a', 'b'], sort=False).first()
        assert_series_equal(result, mseries_result)
        result = mseries.groupby(level=['a', 'b'], sort=True).first()
        assert_series_equal(result, mseries_result.sort_index())

    def test_groupby_reindex_inside_function(self):

        periods = 1000
        ind = DatetimeIndex(start='2012/1/1', freq='5min', periods=periods)
        df = DataFrame({'high': np.arange(
            periods), 'low': np.arange(periods)}, index=ind)

        def agg_before(hour, func, fix=False):
            """
                Run an aggregate func on the subset of data.
            """

            def _func(data):
                d = data.loc[data.index.map(
                    lambda x: x.hour < 11)].dropna()
                if fix:
                    data[data.index[0]]
                if len(d) == 0:
                    return None
                return func(d)

            return _func

        def afunc(data):
            d = data.select(lambda x: x.hour < 11).dropna()
            return np.max(d)

        grouped = df.groupby(lambda x: datetime(x.year, x.month, x.day))
        closure_bad = grouped.agg({'high': agg_before(11, np.max)})
        closure_good = grouped.agg({'high': agg_before(11, np.max, True)})

        assert_frame_equal(closure_bad, closure_good)

    def test_cython_median(self):
        df = DataFrame(np.random.randn(1000))
        df.values[::2] = np.nan

        labels = np.random.randint(0, 50, size=1000).astype(float)
        labels[::17] = np.nan

        result = df.groupby(labels).median()
        exp = df.groupby(labels).agg(nanops.nanmedian)
        assert_frame_equal(result, exp)

        df = DataFrame(np.random.randn(1000, 5))
        rs = df.groupby(labels).agg(np.median)
        xp = df.groupby(labels).median()
        assert_frame_equal(rs, xp)

    def test_median_empty_bins(self):
        df = pd.DataFrame(np.random.randint(0, 44, 500))

        grps = range(0, 55, 5)
        bins = pd.cut(df[0], grps)

        result = df.groupby(bins).median()
        expected = df.groupby(bins).agg(lambda x: x.median())
        assert_frame_equal(result, expected)

    def test_groupby_non_arithmetic_agg_types(self):
        # GH9311, GH6620
        df = pd.DataFrame(
            [{'a': 1, 'b': 1},
             {'a': 1, 'b': 2},
             {'a': 2, 'b': 3},
             {'a': 2, 'b': 4}])

        dtypes = ['int8', 'int16', 'int32', 'int64', 'float32', 'float64']

        grp_exp = {'first': {'df': [{'a': 1, 'b': 1}, {'a': 2, 'b': 3}]},
                   'last': {'df': [{'a': 1, 'b': 2}, {'a': 2, 'b': 4}]},
                   'min': {'df': [{'a': 1, 'b': 1}, {'a': 2, 'b': 3}]},
                   'max': {'df': [{'a': 1, 'b': 2}, {'a': 2, 'b': 4}]},
                   'nth': {'df': [{'a': 1, 'b': 2}, {'a': 2, 'b': 4}],
                           'args': [1]},
                   'count': {'df': [{'a': 1, 'b': 2}, {'a': 2, 'b': 2}],
                             'out_type': 'int64'}}

        for dtype in dtypes:
            df_in = df.copy()
            df_in['b'] = df_in.b.astype(dtype)

            for method, data in compat.iteritems(grp_exp):
                if 'args' not in data:
                    data['args'] = []

                if 'out_type' in data:
                    out_type = data['out_type']
                else:
                    out_type = dtype

                exp = data['df']
                df_out = pd.DataFrame(exp)

                df_out['b'] = df_out.b.astype(out_type)
                df_out.set_index('a', inplace=True)

                grpd = df_in.groupby('a')
                t = getattr(grpd, method)(*data['args'])
                assert_frame_equal(t, df_out)

    def test_groupby_non_arithmetic_agg_intlike_precision(self):
        # GH9311, GH6620
        c = 24650000000000000

        inputs = ((Timestamp('2011-01-15 12:50:28.502376'),
                   Timestamp('2011-01-20 12:50:28.593448')), (1 + c, 2 + c))

        for i in inputs:
            df = pd.DataFrame([{'a': 1, 'b': i[0]}, {'a': 1, 'b': i[1]}])

            grp_exp = {'first': {'expected': i[0]},
                       'last': {'expected': i[1]},
                       'min': {'expected': i[0]},
                       'max': {'expected': i[1]},
                       'nth': {'expected': i[1],
                               'args': [1]},
                       'count': {'expected': 2}}

            for method, data in compat.iteritems(grp_exp):
                if 'args' not in data:
                    data['args'] = []

                grpd = df.groupby('a')
                res = getattr(grpd, method)(*data['args'])
                assert res.iloc[0].b == data['expected']

    def test_groupby_multiindex_missing_pair(self):
        # GH9049
        df = DataFrame({'group1': ['a', 'a', 'a', 'b'],
                        'group2': ['c', 'c', 'd', 'c'],
                        'value': [1, 1, 1, 5]})
        df = df.set_index(['group1', 'group2'])
        df_grouped = df.groupby(level=['group1', 'group2'], sort=True)

        res = df_grouped.agg('sum')
        idx = MultiIndex.from_tuples(
            [('a', 'c'), ('a', 'd'), ('b', 'c')], names=['group1', 'group2'])
        exp = DataFrame([[2], [1], [5]], index=idx, columns=['value'])

        tm.assert_frame_equal(res, exp)

    def test_groupby_multiindex_not_lexsorted(self):
        # GH 11640

        # define the lexsorted version
        lexsorted_mi = MultiIndex.from_tuples(
            [('a', ''), ('b1', 'c1'), ('b2', 'c2')], names=['b', 'c'])
        lexsorted_df = DataFrame([[1, 3, 4]], columns=lexsorted_mi)
        assert lexsorted_df.columns.is_lexsorted()

        # define the non-lexsorted version
        not_lexsorted_df = DataFrame(columns=['a', 'b', 'c', 'd'],
                                     data=[[1, 'b1', 'c1', 3],
                                           [1, 'b2', 'c2', 4]])
        not_lexsorted_df = not_lexsorted_df.pivot_table(
            index='a', columns=['b', 'c'], values='d')
        not_lexsorted_df = not_lexsorted_df.reset_index()
        assert not not_lexsorted_df.columns.is_lexsorted()

        # compare the results
        tm.assert_frame_equal(lexsorted_df, not_lexsorted_df)

        expected = lexsorted_df.groupby('a').mean()
        with tm.assert_produces_warning(PerformanceWarning):
            result = not_lexsorted_df.groupby('a').mean()
        tm.assert_frame_equal(expected, result)

        # a transforming function should work regardless of sort
        # GH 14776
        df = DataFrame({'x': ['a', 'a', 'b', 'a'],
                        'y': [1, 1, 2, 2],
                        'z': [1, 2, 3, 4]}).set_index(['x', 'y'])
        assert not df.index.is_lexsorted()

        for level in [0, 1, [0, 1]]:
            for sort in [False, True]:
                result = df.groupby(level=level, sort=sort).apply(
                    DataFrame.drop_duplicates)
                expected = df
                tm.assert_frame_equal(expected, result)

                result = df.sort_index().groupby(level=level, sort=sort).apply(
                    DataFrame.drop_duplicates)
                expected = df.sort_index()
                tm.assert_frame_equal(expected, result)

    def test_gb_apply_list_of_unequal_len_arrays(self):

        # GH1738
        df = DataFrame({'group1': ['a', 'a', 'a', 'b', 'b', 'b', 'a', 'a', 'a',
                                   'b', 'b', 'b'],
                        'group2': ['c', 'c', 'd', 'd', 'd', 'e', 'c', 'c', 'd',
                                   'd', 'd', 'e'],
                        'weight': [1.1, 2, 3, 4, 5, 6, 2, 4, 6, 8, 1, 2],
                        'value': [7.1, 8, 9, 10, 11, 12, 8, 7, 6, 5, 4, 3]})
        df = df.set_index(['group1', 'group2'])
        df_grouped = df.groupby(level=['group1', 'group2'], sort=True)

        def noddy(value, weight):
            out = np.array(value * weight).repeat(3)
            return out

        # the kernel function returns arrays of unequal length
        # pandas sniffs the first one, sees it's an array and not
        # a list, and assumed the rest are of equal length
        # and so tries a vstack

        # don't die
        df_grouped.apply(lambda x: noddy(x.value, x.weight))

    def test_fill_constistency(self):

        # GH9221
        # pass thru keyword arguments to the generated wrapper
        # are set if the passed kw is None (only)
        df = DataFrame(index=pd.MultiIndex.from_product(
            [['value1', 'value2'], date_range('2014-01-01', '2014-01-06')]),
            columns=Index(
            ['1', '2'], name='id'))
        df['1'] = [np.nan, 1, np.nan, np.nan, 11, np.nan, np.nan, 2, np.nan,
                   np.nan, 22, np.nan]
        df['2'] = [np.nan, 3, np.nan, np.nan, 33, np.nan, np.nan, 4, np.nan,
                   np.nan, 44, np.nan]

        expected = df.groupby(level=0, axis=0).fillna(method='ffill')
        result = df.T.groupby(level=0, axis=1).fillna(method='ffill').T
        assert_frame_equal(result, expected)

    def test_index_label_overlaps_location(self):
        # checking we don't have any label/location confusion in the
        # the wake of GH5375
        df = DataFrame(list('ABCDE'), index=[2, 0, 2, 1, 1])
        g = df.groupby(list('ababb'))
        actual = g.filter(lambda x: len(x) > 2)
        expected = df.iloc[[1, 3, 4]]
        assert_frame_equal(actual, expected)

        ser = df[0]
        g = ser.groupby(list('ababb'))
        actual = g.filter(lambda x: len(x) > 2)
        expected = ser.take([1, 3, 4])
        assert_series_equal(actual, expected)

        # ... and again, with a generic Index of floats
        df.index = df.index.astype(float)
        g = df.groupby(list('ababb'))
        actual = g.filter(lambda x: len(x) > 2)
        expected = df.iloc[[1, 3, 4]]
        assert_frame_equal(actual, expected)

        ser = df[0]
        g = ser.groupby(list('ababb'))
        actual = g.filter(lambda x: len(x) > 2)
        expected = ser.take([1, 3, 4])
        assert_series_equal(actual, expected)

    def test_groupby_cumprod(self):
        # GH 4095
        df = pd.DataFrame({'key': ['b'] * 10, 'value': 2})

        actual = df.groupby('key')['value'].cumprod()
        expected = df.groupby('key')['value'].apply(lambda x: x.cumprod())
        expected.name = 'value'
        tm.assert_series_equal(actual, expected)

        df = pd.DataFrame({'key': ['b'] * 100, 'value': 2})
        actual = df.groupby('key')['value'].cumprod()
        # if overflows, groupby product casts to float
        # while numpy passes back invalid values
        df['value'] = df['value'].astype(float)
        expected = df.groupby('key')['value'].apply(lambda x: x.cumprod())
        expected.name = 'value'
        tm.assert_series_equal(actual, expected)

    def test_ops_general(self):
        ops = [('mean', np.mean),
               ('median', np.median),
               ('std', np.std),
               ('var', np.var),
               ('sum', np.sum),
               ('prod', np.prod),
               ('min', np.min),
               ('max', np.max),
               ('first', lambda x: x.iloc[0]),
               ('last', lambda x: x.iloc[-1]),
               ('count', np.size), ]
        try:
            from scipy.stats import sem
        except ImportError:
            pass
        else:
            ops.append(('sem', sem))
        df = DataFrame(np.random.randn(1000))
        labels = np.random.randint(0, 50, size=1000).astype(float)

        for op, targop in ops:
            result = getattr(df.groupby(labels), op)().astype(float)
            expected = df.groupby(labels).agg(targop)
            try:
                tm.assert_frame_equal(result, expected)
            except BaseException as exc:
                exc.args += ('operation: %s' % op, )
                raise

    def test_max_nan_bug(self):
        raw = """,Date,app,File
2013-04-23,2013-04-23 00:00:00,,log080001.log
2013-05-06,2013-05-06 00:00:00,,log.log
2013-05-07,2013-05-07 00:00:00,OE,xlsx"""

        df = pd.read_csv(StringIO(raw), parse_dates=[0])
        gb = df.groupby('Date')
        r = gb[['File']].max()
        e = gb['File'].max().to_frame()
        tm.assert_frame_equal(r, e)
        assert not r['File'].isna().any()

    def test_nlargest(self):
        a = Series([1, 3, 5, 7, 2, 9, 0, 4, 6, 10])
        b = Series(list('a' * 5 + 'b' * 5))
        gb = a.groupby(b)
        r = gb.nlargest(3)
        e = Series([
            7, 5, 3, 10, 9, 6
        ], index=MultiIndex.from_arrays([list('aaabbb'), [3, 2, 1, 9, 5, 8]]))
        tm.assert_series_equal(r, e)

        a = Series([1, 1, 3, 2, 0, 3, 3, 2, 1, 0])
        gb = a.groupby(b)
        e = Series([
            3, 2, 1, 3, 3, 2
        ], index=MultiIndex.from_arrays([list('aaabbb'), [2, 3, 1, 6, 5, 7]]))
        assert_series_equal(gb.nlargest(3, keep='last'), e)

    def test_nsmallest(self):
        a = Series([1, 3, 5, 7, 2, 9, 0, 4, 6, 10])
        b = Series(list('a' * 5 + 'b' * 5))
        gb = a.groupby(b)
        r = gb.nsmallest(3)
        e = Series([
            1, 2, 3, 0, 4, 6
        ], index=MultiIndex.from_arrays([list('aaabbb'), [0, 4, 1, 6, 7, 8]]))
        tm.assert_series_equal(r, e)

        a = Series([1, 1, 3, 2, 0, 3, 3, 2, 1, 0])
        gb = a.groupby(b)
        e = Series([
            0, 1, 1, 0, 1, 2
        ], index=MultiIndex.from_arrays([list('aaabbb'), [4, 1, 0, 9, 8, 7]]))
        assert_series_equal(gb.nsmallest(3, keep='last'), e)

    def test_transform_doesnt_clobber_ints(self):
        # GH 7972
        n = 6
        x = np.arange(n)
        df = DataFrame({'a': x // 2, 'b': 2.0 * x, 'c': 3.0 * x})
        df2 = DataFrame({'a': x // 2 * 1.0, 'b': 2.0 * x, 'c': 3.0 * x})

        gb = df.groupby('a')
        result = gb.transform('mean')

        gb2 = df2.groupby('a')
        expected = gb2.transform('mean')
        tm.assert_frame_equal(result, expected)

    def test_groupby_apply_all_none(self):
        # Tests to make sure no errors if apply function returns all None
        # values. Issue 9684.
        test_df = DataFrame({'groups': [0, 0, 1, 1],
                             'random_vars': [8, 7, 4, 5]})

        def test_func(x):
            pass

        result = test_df.groupby('groups').apply(test_func)
        expected = DataFrame()
        tm.assert_frame_equal(result, expected)

    def test_groupby_apply_none_first(self):
        # GH 12824. Tests if apply returns None first.
        test_df1 = DataFrame({'groups': [1, 1, 1, 2], 'vars': [0, 1, 2, 3]})
        test_df2 = DataFrame({'groups': [1, 2, 2, 2], 'vars': [0, 1, 2, 3]})

        def test_func(x):
            if x.shape[0] < 2:
                return None
            return x.iloc[[0, -1]]

        result1 = test_df1.groupby('groups').apply(test_func)
        result2 = test_df2.groupby('groups').apply(test_func)
        index1 = MultiIndex.from_arrays([[1, 1], [0, 2]],
                                        names=['groups', None])
        index2 = MultiIndex.from_arrays([[2, 2], [1, 3]],
                                        names=['groups', None])
        expected1 = DataFrame({'groups': [1, 1], 'vars': [0, 2]},
                              index=index1)
        expected2 = DataFrame({'groups': [2, 2], 'vars': [1, 3]},
                              index=index2)
        tm.assert_frame_equal(result1, expected1)
        tm.assert_frame_equal(result2, expected2)

    def test_groupby_preserves_sort(self):
        # Test to ensure that groupby always preserves sort order of original
        # object. Issue #8588 and #9651

        df = DataFrame(
            {'int_groups': [3, 1, 0, 1, 0, 3, 3, 3],
             'string_groups': ['z', 'a', 'z', 'a', 'a', 'g', 'g', 'g'],
             'ints': [8, 7, 4, 5, 2, 9, 1, 1],
             'floats': [2.3, 5.3, 6.2, -2.4, 2.2, 1.1, 1.1, 5],
             'strings': ['z', 'd', 'a', 'e', 'word', 'word2', '42', '47']})

        # Try sorting on different types and with different group types
        for sort_column in ['ints', 'floats', 'strings', ['ints', 'floats'],
                            ['ints', 'strings']]:
            for group_column in ['int_groups', 'string_groups',
                                 ['int_groups', 'string_groups']]:

                df = df.sort_values(by=sort_column)

                g = df.groupby(group_column)

                def test_sort(x):
                    assert_frame_equal(x, x.sort_values(by=sort_column))

                g.apply(test_sort)

    def test_numpy_compat(self):
        # see gh-12811
        df = pd.DataFrame({'A': [1, 2, 1], 'B': [1, 2, 3]})
        g = df.groupby('A')

        msg = "numpy operations are not valid with groupby"

        for func in ('mean', 'var', 'std', 'cumprod', 'cumsum'):
            tm.assert_raises_regex(UnsupportedFunctionCall, msg,
                                   getattr(g, func), 1, 2, 3)
            tm.assert_raises_regex(UnsupportedFunctionCall, msg,
                                   getattr(g, func), foo=1)

    def test_group_shift_with_null_key(self):
        # This test is designed to replicate the segfault in issue #13813.
        n_rows = 1200

        # Generate a moderately large dataframe with occasional missing
        # values in column `B`, and then group by [`A`, `B`]. This should
        # force `-1` in `labels` array of `g.grouper.group_info` exactly
        # at those places, where the group-by key is partilly missing.
        df = DataFrame([(i % 12, i % 3 if i % 3 else np.nan, i)
                        for i in range(n_rows)], dtype=float,
                       columns=["A", "B", "Z"], index=None)
        g = df.groupby(["A", "B"])

        expected = DataFrame([(i + 12 if i % 3 and i < n_rows - 12
                               else np.nan)
                              for i in range(n_rows)], dtype=float,
                             columns=["Z"], index=None)
        result = g.shift(-1)

        assert_frame_equal(result, expected)

    def test_pivot_table_values_key_error(self):
        # This test is designed to replicate the error in issue #14938
        df = pd.DataFrame({'eventDate':
                           pd.date_range(pd.datetime.today(),
                                         periods=20, freq='M').tolist(),
                           'thename': range(0, 20)})

        df['year'] = df.set_index('eventDate').index.year
        df['month'] = df.set_index('eventDate').index.month

        with pytest.raises(KeyError):
            df.reset_index().pivot_table(index='year', columns='month',
                                         values='badname', aggfunc='count')

    def test_cummin_cummax(self):
        # GH 15048
        num_types = [np.int32, np.int64, np.float32, np.float64]
        num_mins = [np.iinfo(np.int32).min, np.iinfo(np.int64).min,
                    np.finfo(np.float32).min, np.finfo(np.float64).min]
        num_max = [np.iinfo(np.int32).max, np.iinfo(np.int64).max,
                   np.finfo(np.float32).max, np.finfo(np.float64).max]
        base_df = pd.DataFrame({'A': [1, 1, 1, 1, 2, 2, 2, 2],
                                'B': [3, 4, 3, 2, 2, 3, 2, 1]})
        expected_mins = [3, 3, 3, 2, 2, 2, 2, 1]
        expected_maxs = [3, 4, 4, 4, 2, 3, 3, 3]

        for dtype, min_val, max_val in zip(num_types, num_mins, num_max):
            df = base_df.astype(dtype)

            # cummin
            expected = pd.DataFrame({'B': expected_mins}).astype(dtype)
            result = df.groupby('A').cummin()
            tm.assert_frame_equal(result, expected)
            result = df.groupby('A').B.apply(lambda x: x.cummin()).to_frame()
            tm.assert_frame_equal(result, expected)

            # Test cummin w/ min value for dtype
            df.loc[[2, 6], 'B'] = min_val
            expected.loc[[2, 3, 6, 7], 'B'] = min_val
            result = df.groupby('A').cummin()
            tm.assert_frame_equal(result, expected)
            expected = df.groupby('A').B.apply(lambda x: x.cummin()).to_frame()
            tm.assert_frame_equal(result, expected)

            # cummax
            expected = pd.DataFrame({'B': expected_maxs}).astype(dtype)
            result = df.groupby('A').cummax()
            tm.assert_frame_equal(result, expected)
            result = df.groupby('A').B.apply(lambda x: x.cummax()).to_frame()
            tm.assert_frame_equal(result, expected)

            # Test cummax w/ max value for dtype
            df.loc[[2, 6], 'B'] = max_val
            expected.loc[[2, 3, 6, 7], 'B'] = max_val
            result = df.groupby('A').cummax()
            tm.assert_frame_equal(result, expected)
            expected = df.groupby('A').B.apply(lambda x: x.cummax()).to_frame()
            tm.assert_frame_equal(result, expected)

        # Test nan in some values
        base_df.loc[[0, 2, 4, 6], 'B'] = np.nan
        expected = pd.DataFrame({'B': [np.nan, 4, np.nan, 2,
                                       np.nan, 3, np.nan, 1]})
        result = base_df.groupby('A').cummin()
        tm.assert_frame_equal(result, expected)
        expected = (base_df.groupby('A')
                           .B
                           .apply(lambda x: x.cummin())
                           .to_frame())
        tm.assert_frame_equal(result, expected)

        expected = pd.DataFrame({'B': [np.nan, 4, np.nan, 4,
                                       np.nan, 3, np.nan, 3]})
        result = base_df.groupby('A').cummax()
        tm.assert_frame_equal(result, expected)
        expected = (base_df.groupby('A')
                           .B
                           .apply(lambda x: x.cummax())
                           .to_frame())
        tm.assert_frame_equal(result, expected)

        # Test nan in entire column
        base_df['B'] = np.nan
        expected = pd.DataFrame({'B': [np.nan] * 8})
        result = base_df.groupby('A').cummin()
        tm.assert_frame_equal(expected, result)
        result = base_df.groupby('A').B.apply(lambda x: x.cummin()).to_frame()
        tm.assert_frame_equal(expected, result)
        result = base_df.groupby('A').cummax()
        tm.assert_frame_equal(expected, result)
        result = base_df.groupby('A').B.apply(lambda x: x.cummax()).to_frame()
        tm.assert_frame_equal(expected, result)

        # GH 15561
        df = pd.DataFrame(dict(a=[1], b=pd.to_datetime(['2001'])))
        expected = pd.Series(pd.to_datetime('2001'), index=[0], name='b')
        for method in ['cummax', 'cummin']:
            result = getattr(df.groupby('a')['b'], method)()
            tm.assert_series_equal(expected, result)

        # GH 15635
        df = pd.DataFrame(dict(a=[1, 2, 1], b=[2, 1, 1]))
        result = df.groupby('a').b.cummax()
        expected = pd.Series([2, 1, 2], name='b')
        tm.assert_series_equal(result, expected)

        df = pd.DataFrame(dict(a=[1, 2, 1], b=[1, 2, 2]))
        result = df.groupby('a').b.cummin()
        expected = pd.Series([1, 2, 1], name='b')
        tm.assert_series_equal(result, expected)

    def test_apply_numeric_coercion_when_datetime(self):
        # In the past, group-by/apply operations have been over-eager
        # in converting dtypes to numeric, in the presence of datetime
        # columns.  Various GH issues were filed, the reproductions
        # for which are here.

        # GH 15670
        df = pd.DataFrame({'Number': [1, 2],
                           'Date': ["2017-03-02"] * 2,
                           'Str': ["foo", "inf"]})
        expected = df.groupby(['Number']).apply(lambda x: x.iloc[0])
        df.Date = pd.to_datetime(df.Date)
        result = df.groupby(['Number']).apply(lambda x: x.iloc[0])
        tm.assert_series_equal(result['Str'], expected['Str'])

        # GH 15421
        df = pd.DataFrame({'A': [10, 20, 30],
                           'B': ['foo', '3', '4'],
                           'T': [pd.Timestamp("12:31:22")] * 3})

        def get_B(g):
            return g.iloc[0][['B']]
        result = df.groupby('A').apply(get_B)['B']
        expected = df.B
        expected.index = df.A
        tm.assert_series_equal(result, expected)

        # GH 14423
        def predictions(tool):
            out = pd.Series(index=['p1', 'p2', 'useTime'], dtype=object)
            if 'step1' in list(tool.State):
                out['p1'] = str(tool[tool.State == 'step1'].Machine.values[0])
            if 'step2' in list(tool.State):
                out['p2'] = str(tool[tool.State == 'step2'].Machine.values[0])
                out['useTime'] = str(
                    tool[tool.State == 'step2'].oTime.values[0])
            return out
        df1 = pd.DataFrame({'Key': ['B', 'B', 'A', 'A'],
                            'State': ['step1', 'step2', 'step1', 'step2'],
                            'oTime': ['', '2016-09-19 05:24:33',
                                      '', '2016-09-19 23:59:04'],
                            'Machine': ['23', '36L', '36R', '36R']})
        df2 = df1.copy()
        df2.oTime = pd.to_datetime(df2.oTime)
        expected = df1.groupby('Key').apply(predictions).p1
        result = df2.groupby('Key').apply(predictions).p1
        tm.assert_series_equal(expected, result)

    def test_pipe(self):
        # Test the pipe method of DataFrameGroupBy.
        # Issue #17871

        random_state = np.random.RandomState(1234567890)

        df = DataFrame({'A': ['foo', 'bar', 'foo', 'bar',
                              'foo', 'bar', 'foo', 'foo'],
                        'B': random_state.randn(8),
                        'C': random_state.randn(8)})

        def f(dfgb):
            return dfgb.B.max() - dfgb.C.min().min()

        def square(srs):
            return srs ** 2

        # Note that the transformations are
        # GroupBy -> Series
        # Series -> Series
        # This then chains the GroupBy.pipe and the
        # NDFrame.pipe methods
        result = df.groupby('A').pipe(f).pipe(square)

        index = Index([u'bar', u'foo'], dtype='object', name=u'A')
        expected = pd.Series([8.99110003361, 8.17516964785], name='B',
                             index=index)

        assert_series_equal(expected, result)

    def test_pipe_args(self):
        # Test passing args to the pipe method of DataFrameGroupBy.
        # Issue #17871

        df = pd.DataFrame({'group': ['A', 'A', 'B', 'B', 'C'],
                           'x': [1.0, 2.0, 3.0, 2.0, 5.0],
                           'y': [10.0, 100.0, 1000.0, -100.0, -1000.0]})

        def f(dfgb, arg1):
            return (dfgb.filter(lambda grp: grp.y.mean() > arg1, dropna=False)
                        .groupby(dfgb.grouper))

        def g(dfgb, arg2):
            return dfgb.sum() / dfgb.sum().sum() + arg2

        def h(df, arg3):
            return df.x + df.y - arg3

        result = (df
                  .groupby('group')
                  .pipe(f, 0)
                  .pipe(g, 10)
                  .pipe(h, 100))

        # Assert the results here
        index = pd.Index(['A', 'B', 'C'], name='group')
        expected = pd.Series([-79.5160891089, -78.4839108911, None],
                             index=index)

        assert_series_equal(expected, result)

        # test SeriesGroupby.pipe
        ser = pd.Series([1, 1, 2, 2, 3, 3])
        result = ser.groupby(ser).pipe(lambda grp: grp.sum() * grp.count())

        expected = pd.Series([4, 8, 12], index=pd.Int64Index([1, 2, 3]))

        assert_series_equal(result, expected)

    def test_empty_dataframe_groupby(self):
        # GH8093
        df = DataFrame(columns=['A', 'B', 'C'])

        result = df.groupby('A').sum()
        expected = DataFrame(columns=['B', 'C'], dtype=np.float64)
        expected.index.name = 'A'

        assert_frame_equal(result, expected)

    def test_tuple_warns(self):
        # https://github.com/pandas-dev/pandas/issues/18314
        df = pd.DataFrame({('a', 'b'): [1, 1, 2, 2], 'a': [1, 1, 1, 2],
                           'b': [1, 2, 2, 2], 'c': [1, 1, 1, 1]})
        with tm.assert_produces_warning(FutureWarning) as w:
            df[['a', 'b', 'c']].groupby(('a', 'b')).c.mean()

        assert "Interpreting tuple 'by' as a list" in str(w[0].message)

        with tm.assert_produces_warning(None):
            df.groupby(('a', 'b')).c.mean()

    def test_tuple_warns_unhashable(self):
        # https://github.com/pandas-dev/pandas/issues/18314
        business_dates = date_range(start='4/1/2014', end='6/30/2014',
                                    freq='B')
        df = DataFrame(1, index=business_dates, columns=['a', 'b'])

        with tm.assert_produces_warning(FutureWarning) as w:
            df.groupby((df.index.year, df.index.month)).nth([0, 3, -1])

        assert "Interpreting tuple 'by' as a list" in str(w[0].message)

    def test_tuple_correct_keyerror(self):
        # https://github.com/pandas-dev/pandas/issues/18798
        df = pd.DataFrame(1, index=range(3),
                          columns=pd.MultiIndex.from_product([[1, 2],
                                                              [3, 4]]))
        with tm.assert_raises_regex(KeyError, "(7, 8)"):
            df.groupby((7, 8)).mean()


def _check_groupby(df, result, keys, field, f=lambda x: x.sum()):
    tups = lmap(tuple, df[keys].values)
    tups = com._asarray_tuplesafe(tups)
    expected = f(df.groupby(tups)[field])
    for k, v in compat.iteritems(expected):
        assert (result[k] == v)
