"""Tabla de precios por modelo y cálculo del costo de cada llamada.

Los precios están en USD por millón de tokens. El costo no se redondea: una
pregunta corta nunca debe reportar 0 por error.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Union

TOKENS_PER_UNIT = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """Precio de un modelo en USD por millón de tokens.

    :param input_usd: Precio de los tokens de entrada.
    :type input_usd: float
    :param output_usd: Precio de los tokens de salida.
    :type output_usd: float
    """

    input_usd: float
    output_usd: float


def _price_from(name: str, raw: object) -> ModelPrice:
    """Valida y convierte el precio de un modelo leído del JSON.

    :param name: Nombre del modelo.
    :type name: str
    :param raw: Objeto con ``input`` y ``output``.
    :type raw: object
    :return: El precio validado.
    :rtype: ModelPrice
    :raises ValueError: Si falta un precio o no es un número de 0 o más.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"price of model {name!r} must be an object")
    values = []
    for key in ("input", "output"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"price {key!r} of model {name!r} must be a number")
        if value < 0:
            raise ValueError(f"price {key!r} of model {name!r} must not be negative")
        values.append(float(value))
    return ModelPrice(input_usd=values[0], output_usd=values[1])


class PriceTable:
    """Precios de los modelos conocidos.

    :param prices: Precio por nombre de modelo.
    :type prices: Mapping[str, ModelPrice]
    """

    def __init__(self, prices: Mapping[str, ModelPrice]) -> None:
        self._prices: Dict[str, ModelPrice] = dict(prices)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "PriceTable":
        """Carga los precios de un archivo JSON con la clave ``models``.

        :param path: Ruta al archivo de precios.
        :type path: str or pathlib.Path
        :return: La tabla de precios.
        :rtype: PriceTable
        :raises ValueError: Si el archivo no existe o su formato es inválido.
        """
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as error:
            raise ValueError(f"cannot read the prices file: {path}") from error
        except ValueError as error:
            raise ValueError(f"the prices file is not valid JSON: {path}") from error
        models = document.get("models") if isinstance(document, dict) else None
        if not isinstance(models, dict):
            raise ValueError(f"the prices file has no 'models' object: {path}")
        return cls({name: _price_from(name, raw) for name, raw in models.items()})

    def has_price(self, model: str) -> bool:
        """Indica si el modelo tiene precio.

        :param model: Nombre del modelo.
        :type model: str
        :return: ``True`` si está en la tabla.
        :rtype: bool
        """
        return model in self._prices

    def cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calcula el costo de una llamada, sin redondear.

        :param model: Nombre del modelo.
        :type model: str
        :param input_tokens: Tokens de entrada.
        :type input_tokens: int
        :param output_tokens: Tokens de salida.
        :type output_tokens: int
        :return: Costo en USD.
        :rtype: float
        :raises ValueError: Si el modelo no tiene precio.
        """
        price = self._prices.get(model)
        if price is None:
            raise ValueError(f"model without price: {model!r}")
        total = input_tokens * price.input_usd + output_tokens * price.output_usd
        return total / TOKENS_PER_UNIT
