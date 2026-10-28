from decimal import Decimal
import unicodedata
from difflib import SequenceMatcher


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c)).strip()


def candidates(name, products):
    """Sugerir coincidencias; nunca unir automáticamente productos distintos."""
    q = normalize(name)
    return sorted([(SequenceMatcher(None, q, normalize(p['nombre'])).ratio(), p)
                   for p in products], key=lambda x: x[0], reverse=True)[:5]


def weighted_cost(stock, cost, received, purchase):
    stock, cost, received, purchase = map(Decimal, map(str, (stock, cost, received, purchase)))
    if stock < 0 or received <= 0 or min(cost, purchase) < 0:
        raise ValueError('Cantidades o costos inválidos')
    return (stock * cost + received * purchase) / (stock + received)
