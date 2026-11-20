"""Catálogo cerrado de clientes y conceptos para los borradores de factura.

Se lee una vez al arrancar desde ``CLIENTES_PATH`` y ``CONCEPTOS_PATH`` y se
valida su contenido. Las menciones se buscan sin acentos ni mayúsculas, con
límites de palabra; gana el alias más largo y no hay traslapes.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, TypeVar, Union

RFC_FORMAT = re.compile(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}")
MONEY_FORMAT = re.compile(r"\d+\.\d{2}")


@dataclass(frozen=True)
class Client:
    """Cliente del catálogo.

    :param id: Id del cliente (``CLI-001``).
    :type id: str
    :param nombre: Razón social.
    :type nombre: str
    :param rfc: RFC completo.
    :type rfc: str
    :param aliases: Formas de mencionarlo, ya normalizadas.
    :type aliases: tuple[str, ...]
    """

    id: str  # pylint: disable=invalid-name
    nombre: str
    rfc: str
    aliases: Tuple[str, ...]


@dataclass(frozen=True)
class Concept:
    """Concepto facturable del catálogo.

    :param id: Id del concepto (``CON-001``).
    :type id: str
    :param descripcion: Descripción que va en la línea.
    :type descripcion: str
    :param unidad: Unidad de medida.
    :type unidad: str
    :param precio_unitario: Precio en MXN, con 2 decimales.
    :type precio_unitario: Decimal
    :param aliases: Formas de mencionarlo, ya normalizadas.
    :type aliases: tuple[str, ...]
    """

    id: str  # pylint: disable=invalid-name
    descripcion: str
    unidad: str
    precio_unitario: Decimal
    aliases: Tuple[str, ...]


Entry = TypeVar("Entry", Client, Concept)


@dataclass(frozen=True)
class Mention:
    """Un alias encontrado dentro de un texto normalizado.

    :param start: Posición donde empieza.
    :type start: int
    :param end: Posición donde termina (exclusiva).
    :type end: int
    :param alias: Alias encontrado, normalizado.
    :type alias: str
    :param entry: Cliente o concepto al que pertenece.
    :type entry: Client or Concept
    """

    start: int
    end: int
    alias: str
    entry: Union[Client, Concept]


def normalize(text: str) -> str:
    """Quita acentos y mayúsculas y junta los espacios repetidos.

    :param text: Texto original.
    :type text: str
    :return: Texto normalizado, por ejemplo ``ferreteria lopez``.
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.casefold().split())


def find_mentions(text: str, entries: Sequence[Entry]) -> List[Mention]:
    """Busca los alias de ``entries`` en el texto.

    Compara contra el texto normalizado y con límites de palabra. Si dos
    menciones se traslapan gana la más larga.

    :param text: Texto donde buscar (se normaliza aquí).
    :type text: str
    :param entries: Clientes o conceptos del catálogo.
    :type entries: Sequence[Client] or Sequence[Concept]
    :return: Menciones sin traslapes, en el orden en que aparecen.
    :rtype: list[Mention]
    """
    folded = normalize(text)
    candidates = []
    for entry in entries:
        for alias in entry.aliases:
            pattern = re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)")
            for match in pattern.finditer(folded):
                candidates.append(Mention(match.start(), match.end(), alias, entry))
    candidates.sort(key=lambda found: (found.start - found.end, found.start))
    chosen: List[Mention] = []
    for mention in candidates:
        if not any(_overlaps(mention, kept) for kept in chosen):
            chosen.append(mention)
    return sorted(chosen, key=lambda found: found.start)


def _overlaps(first: Mention, second: Mention) -> bool:
    """Indica si dos menciones comparten algún carácter.

    :param first: Una mención.
    :type first: Mention
    :param second: Otra mención.
    :type second: Mention
    :return: ``True`` si se traslapan.
    :rtype: bool
    """
    return first.start < second.end and second.start < first.end


def _read_list(path: str, name: str) -> list:
    """Lee un archivo JSON que debe ser una lista.

    :param path: Ruta del archivo.
    :type path: str
    :param name: Variable de entorno de la ruta, para el mensaje de error.
    :type name: str
    :return: La lista leída.
    :rtype: list
    :raises ValueError: Si no se puede leer o no es una lista.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{name} cannot be read: {type(error).__name__}") from None
    if not isinstance(data, list) or not data:
        raise ValueError(f"{name} must be a non-empty JSON list")
    return data


def _text_field(item: object, field_name: str, name: str) -> str:
    """Lee un campo de texto no vacío de una entrada del catálogo.

    :param item: Entrada del JSON.
    :type item: object
    :param field_name: Campo a leer.
    :type field_name: str
    :param name: Variable de entorno del archivo, para el mensaje de error.
    :type name: str
    :return: El texto sin espacios a los lados.
    :rtype: str
    :raises ValueError: Si la entrada no es un objeto o el campo no es texto.
    """
    value = item.get(field_name) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} has an entry without a valid {field_name!r}")
    return value.strip()


def _aliases(item: dict, name: str) -> Tuple[str, ...]:
    """Lee y normaliza los alias de una entrada.

    :param item: Entrada del JSON.
    :type item: dict
    :param name: Variable de entorno del archivo, para el mensaje de error.
    :type name: str
    :return: Alias normalizados, sin repetidos.
    :rtype: tuple[str, ...]
    :raises ValueError: Si no hay alias o alguno está vacío.
    """
    raw = item.get("aliases")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{name} has an entry without aliases")
    aliases = []
    for alias in raw:
        folded = normalize(alias) if isinstance(alias, str) else ""
        if not folded:
            raise ValueError(f"{name} has an empty alias")
        if folded not in aliases:
            aliases.append(folded)
    return tuple(aliases)


def _price(item: dict, name: str) -> Decimal:
    """Lee el precio unitario: texto con 2 decimales, mayor que cero.

    :param item: Entrada del JSON.
    :type item: dict
    :param name: Variable de entorno del archivo, para el mensaje de error.
    :type name: str
    :return: El precio como ``Decimal``.
    :rtype: Decimal
    :raises ValueError: Si el precio no tiene el formato o no es positivo.
    """
    raw = _text_field(item, "precio_unitario", name)
    if not MONEY_FORMAT.fullmatch(raw):
        raise ValueError(f"{name} has a price without the format 0.00")
    try:
        price = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{name} has an invalid price") from None
    if price <= 0:
        raise ValueError(f"{name} has a price that is not positive")
    return price


def _unique_ids(entries: Sequence[Union[Client, Concept]], name: str) -> None:
    """Revisa que los ids no se repitan.

    :param entries: Entradas ya leídas.
    :type entries: Sequence
    :param name: Variable de entorno del archivo, para el mensaje de error.
    :type name: str
    :raises ValueError: Si hay un id repetido.
    """
    ids = [entry.id for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{name} has repeated ids")


def load_clients(path: str) -> Tuple[Client, ...]:
    """Lee y valida ``clientes.json``.

    :param path: Ruta del archivo.
    :type path: str
    :return: Los clientes.
    :rtype: tuple[Client, ...]
    :raises ValueError: Si el archivo o alguna entrada no es válida; el mensaje
        nombra la variable, nunca un RFC.
    """
    name = "CLIENTES_PATH"
    clients = []
    for item in _read_list(path, name):
        rfc = _text_field(item, "rfc", name)
        if not RFC_FORMAT.fullmatch(rfc):
            raise ValueError(f"{name} has an RFC with an invalid format")
        clients.append(
            Client(
                id=_text_field(item, "id", name),
                nombre=_text_field(item, "nombre", name),
                rfc=rfc,
                aliases=_aliases(item, name),
            )
        )
    _unique_ids(clients, name)
    return tuple(clients)


def load_concepts(path: str) -> Tuple[Concept, ...]:
    """Lee y valida ``conceptos.json``.

    :param path: Ruta del archivo.
    :type path: str
    :return: Los conceptos.
    :rtype: tuple[Concept, ...]
    :raises ValueError: Si el archivo o alguna entrada no es válida.
    """
    name = "CONCEPTOS_PATH"
    concepts = []
    for item in _read_list(path, name):
        concepts.append(
            Concept(
                id=_text_field(item, "id", name),
                descripcion=_text_field(item, "descripcion", name),
                unidad=_text_field(item, "unidad", name),
                precio_unitario=_price(item, name),
                aliases=_aliases(item, name),
            )
        )
    _unique_ids(concepts, name)
    return tuple(concepts)


class Catalog:
    """Clientes y conceptos de solo lectura.

    :param clients: Clientes del catálogo.
    :type clients: Sequence[Client]
    :param concepts: Conceptos del catálogo.
    :type concepts: Sequence[Concept]
    """

    def __init__(self, clients: Sequence[Client], concepts: Sequence[Concept]) -> None:
        self.clients: Tuple[Client, ...] = tuple(clients)
        self.concepts: Tuple[Concept, ...] = tuple(concepts)
        self._clients_by_id: Dict[str, Client] = {c.id: c for c in self.clients}
        self._concepts_by_id: Dict[str, Concept] = {c.id: c for c in self.concepts}

    @classmethod
    def from_files(cls, clientes_path: str, conceptos_path: str) -> "Catalog":
        """Lee el catálogo de sus dos archivos JSON.

        :param clientes_path: Ruta de ``clientes.json``.
        :type clientes_path: str
        :param conceptos_path: Ruta de ``conceptos.json``.
        :type conceptos_path: str
        :return: El catálogo validado.
        :rtype: Catalog
        :raises ValueError: Si algún archivo no es válido.
        """
        return cls(load_clients(clientes_path), load_concepts(conceptos_path))

    def client_by_id(self, client_id: str) -> Optional[Client]:
        """Busca un cliente por id.

        :param client_id: Id del cliente.
        :type client_id: str
        :return: El cliente o ``None``.
        :rtype: Client or None
        """
        return self._clients_by_id.get(client_id)

    def concept_by_id(self, concept_id: str) -> Optional[Concept]:
        """Busca un concepto por id.

        :param concept_id: Id del concepto.
        :type concept_id: str
        :return: El concepto o ``None``.
        :rtype: Concept or None
        """
        return self._concepts_by_id.get(concept_id)

    def find_client(self, text: str) -> Optional[Client]:
        """Resuelve el primer cliente mencionado en el texto.

        :param text: Texto con el que se menciona al cliente.
        :type text: str
        :return: El cliente o ``None`` si ningún alias aparece.
        :rtype: Client or None
        """
        mentions = find_mentions(text, self.clients)
        return mentions[0].entry if mentions else None  # type: ignore[return-value]

    def find_concept(self, text: str) -> Optional[Concept]:
        """Resuelve el primer concepto mencionado en el texto.

        :param text: Texto con el que se menciona el concepto.
        :type text: str
        :return: El concepto o ``None`` si ningún alias aparece.
        :rtype: Concept or None
        """
        mentions = find_mentions(text, self.concepts)
        return mentions[0].entry if mentions else None  # type: ignore[return-value]
