from decimal import Decimal
import pytest
from domain import weighted_cost, candidates


def test_weighting_uses_quantities_not_simple_average():
    assert weighted_cost(10, 1000, 20, 1300) == Decimal('1200')


def test_empty_stock_uses_purchase_cost():
    assert weighted_cost(0, 999, 5, 200) == Decimal('200')


def test_reject_negative_quantity():
    with pytest.raises(ValueError):
        weighted_cost(1, 100, -1, 100)


def test_name_matching_ignores_accents_but_does_not_merge():
    products = [{'id':'a','nombre':'CAFÉ 250 g'}, {'id':'b','nombre':'Té 100 g'}]
    result = candidates('cafe 250 g', products)
    assert result[0][1]['id']=='a'
    assert len(products)==2
