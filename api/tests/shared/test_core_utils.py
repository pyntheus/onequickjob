from datetime import date, time

import pytest

from app.core import crypto, geo, phone, timeutil


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("07700 900123", "+447700900123"),
        ("+44 7700 900123", "+447700900123"),
        ("0044 7700 900123", "+447700900123"),
        ("447700900123", "+447700900123"),
        ("(01494) 712345", "+441494712345"),
        ("+44 (0)7700 900123", "+447700900123"),
    ],
)
def test_phone_to_e164(raw, e164):
    assert phone.to_e164(raw) == e164


@pytest.mark.parametrize("raw", ["12345", "+1 202 555 0100", "07700", "abc", "+44 5555 555555"])
def test_phone_rejects(raw):
    with pytest.raises(phone.InvalidPhone):
        phone.to_e164(raw)


def test_phone_display():
    assert phone.to_national("+447700900123") == "07700 900123"
    assert phone.mask("+447700900123") == "07700 9•••23"


def test_tax_year_boundaries():
    assert timeutil.tax_year(date(2026, 4, 5)) == "2025-26"
    assert timeutil.tax_year(date(2026, 4, 6)) == "2026-27"
    assert timeutil.tax_year(date(2027, 1, 31)) == "2026-27"
    assert timeutil.tax_year_bounds("2026-27") == (date(2026, 4, 6), date(2027, 4, 5))


def test_week_and_london_times():
    assert timeutil.week_start(date(2026, 10, 2)) == date(2026, 9, 28)  # Friday -> Monday
    utc = timeutil.london_datetime(date(2026, 7, 1), time(9, 0))
    assert utc.hour == 8  # BST
    utc = timeutil.london_datetime(date(2026, 12, 1), time(9, 0))
    assert utc.hour == 9  # GMT


def test_postcodes_and_distance():
    assert geo.normalise_postcode("hp157qt") == "HP15 7QT"
    assert geo.district_of("SL7 1AA") == "SL7"
    miles = geo.miles_between(51.6541, -0.7139, 51.6655, -0.7330)  # Hazlemere -> Widmer End
    assert 1.0 < miles < 1.6


def test_tax_identity_sealing():
    sealed = crypto.seal("QQ123456C")
    assert "QQ123456C" not in sealed and crypto.unseal(sealed) == "QQ123456C"
    assert crypto.key_id(sealed) == "t1", "every sealed value records its key id"
    assert crypto.mask_ni("QQ 12 34 56 C") == "QQ •• •• •• C"
    assert crypto.mask_dob("1958-03-14") == "•• / •• / 1958"


def test_duration_text_matches_the_prototype():
    from app.services.wording import duration_text

    assert duration_text(38) == "38 minutes"
    assert duration_text(89) == "89 minutes"
    assert duration_text(90) == "1½ hours"
    assert duration_text(105) == "2 hours"  # 1.75 h rounds half-up to 2
    assert duration_text(510) == "8½ hours"
