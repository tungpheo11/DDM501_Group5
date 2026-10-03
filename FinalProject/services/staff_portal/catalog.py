"""Demo cardholder catalog: real feature rows from the stream CSVs plus seeded, fake identities.

The 23 features sent to the scoring API come unchanged from
``data/processed/stream_normal.csv`` and ``stream_drifted.csv`` (never from the
training data). Names, customer codes, masked card numbers and statement days
are synthetic, generated deterministically from a seed, and stay inside the
portal: they are never sent to the API nor written to ``inference_logs``.
"""

from __future__ import annotations

import csv
import random
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credit_risk.serving.schemas import CreditPredictRequest

FEATURES: tuple[str, ...] = tuple(CreditPredictRequest.model_fields)
_FLOAT_PREFIXES = ("LIMIT_BAL", "BILL_AMT", "PAY_AMT")

STATEMENT_DAYS: tuple[int, ...] = (5, 15, 25)

_FAMILY_NAMES = (
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ",
    "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý",
)  # fmt: skip
_MIDDLE_NAMES = {
    1: ("Văn", "Đức", "Minh", "Quốc", "Hữu", "Gia", "Thành", "Công"),
    2: ("Thị", "Ngọc", "Thu", "Thanh", "Mai", "Khánh", "Phương", "Bích"),
}
_GIVEN_NAMES = {
    1: (
        "An", "Bảo", "Cường", "Dũng", "Hải", "Hiếu", "Hùng", "Khang", "Long", "Nam",
        "Phúc", "Quân", "Sơn", "Tài", "Thắng", "Trung", "Tuấn", "Vinh", "Đạt", "Kiên",
    ),
    2: (
        "Anh", "Chi", "Diệp", "Giang", "Hà", "Hạnh", "Hương", "Lan", "Linh", "My",
        "Ngân", "Nhung", "Oanh", "Quyên", "Thảo", "Trang", "Vy", "Yến", "Uyên", "Xuân",
    ),
}  # fmt: skip


def parse_feature_row(row: Mapping[str, str]) -> dict[str, float | int]:
    """Cast one CSV row to the API payload: amounts as float, codes and statuses as int."""
    payload: dict[str, float | int] = {}
    for name in FEATURES:
        raw = row[name]
        payload[name] = float(raw) if name.startswith(_FLOAT_PREFIXES) else int(float(raw))
    return payload


def load_feature_rows(path: Path) -> list[dict[str, float | int]]:
    """All rows of a stream CSV as API payloads (the label column is dropped)."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [parse_feature_row(row) for row in csv.DictReader(handle)]


def fold_text(text: str) -> str:
    """Lower-case, accent-free form used for search ("Nguyễn Đức" -> "nguyen duc")."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").lower().strip()


@dataclass(frozen=True)
class Cardholder:
    """One demo cardholder: fake identity + real behavioural features."""

    customer_id: str
    full_name: str
    card_last4: str
    statement_day: int
    source: str
    features: Mapping[str, float | int]

    @property
    def card_masked(self) -> str:
        """Card number as shown to staff."""
        return f"**** {self.card_last4}"

    @property
    def age(self) -> int:
        """Age in years."""
        return int(self.features["AGE"])

    @property
    def limit_bal(self) -> float:
        """Current credit limit (NT dollar)."""
        return float(self.features["LIMIT_BAL"])

    @property
    def balance(self) -> float:
        """Latest statement balance."""
        return float(self.features["BILL_AMT1"])

    @property
    def utilization(self) -> float:
        """Latest statement balance over limit (0 when the balance is negative)."""
        return max(self.balance, 0.0) / self.limit_bal if self.limit_bal else 0.0

    @property
    def gender_label(self) -> str:
        """Gender as displayed."""
        return "Nam" if int(self.features["SEX"]) == 1 else "Nữ"

    def payload(self) -> dict[str, Any]:
        """Request body for the scoring API (features only, no identity)."""
        return dict(self.features)


class Catalog:
    """In-memory, read-only list of demo cardholders."""

    def __init__(self, cardholders: Iterable[Cardholder]) -> None:
        self._items = list(cardholders)
        self._by_id = {item.customer_id: item for item in self._items}
        self._index = {item.customer_id: fold_text(f"{item.full_name} {item.customer_id}") for item in self._items}

    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[Cardholder]:
        """Every cardholder in catalog order."""
        return list(self._items)

    def get(self, customer_id: str) -> Cardholder | None:
        """Cardholder by customer code."""
        return self._by_id.get(customer_id)

    def search(self, query: str, limit: int = 20) -> list[Cardholder]:
        """Match by name (accent-insensitive), customer code or the last digits of the card."""
        needle = fold_text(query)
        if not needle:
            return self._items[:limit]
        digits = needle.replace("*", "").replace(" ", "")
        matches = [
            item
            for item in self._items
            if needle in self._index[item.customer_id] or (digits.isdigit() and item.card_last4.endswith(digits))
        ]
        return matches[:limit]

    def by_statement_day(self, day: int | None) -> list[Cardholder]:
        """Cardholders whose statement is cut on ``day`` (all when ``None``)."""
        return [item for item in self._items if day is None or item.statement_day == day]


def _fake_name(rng: random.Random, sex: int) -> str:
    key = 1 if sex == 1 else 2
    return f"{rng.choice(_FAMILY_NAMES)} {rng.choice(_MIDDLE_NAMES[key])} {rng.choice(_GIVEN_NAMES[key])}"


def build_catalog(
    normal_csv: Path, drifted_csv: Path, *, size: int = 200, drifted_share: float = 0.3, seed: int = 2026
) -> Catalog:
    """Sample ``size`` rows (``drifted_share`` of them under 30 from the drifted stream) and attach fake identities."""
    rng = random.Random(seed)
    normal_rows = load_feature_rows(normal_csv)
    drifted_rows = load_feature_rows(drifted_csv)
    drifted_count = min(len(drifted_rows), round(size * drifted_share))
    normal_count = min(len(normal_rows), size - drifted_count)
    picked = [("normal", row) for row in rng.sample(normal_rows, normal_count)]
    picked += [("genz", row) for row in rng.sample(drifted_rows, drifted_count)]
    rng.shuffle(picked)

    customer_numbers = rng.sample(range(100_000, 1_000_000), len(picked))
    card_numbers = rng.sample(range(1_000, 10_000), len(picked))
    return Catalog(
        Cardholder(
            customer_id=f"KH{number:06d}",
            full_name=_fake_name(rng, int(row["SEX"])),
            card_last4=f"{card:04d}",
            statement_day=rng.choice(STATEMENT_DAYS),
            source=source,
            features=row,
        )
        for (source, row), number, card in zip(picked, customer_numbers, card_numbers, strict=True)
    )
