"""The vault's cipher - plan 01 D3 - proved on the primitive and on the row.

AES-256-GCM with the row's own `(id, user_id)` bound in as associated data.
The binding is the property worth a test file: a ciphertext copied under
another user's id, or another credential id, or read with another master key,
must FAIL TO AUTHENTICATE - not decrypt to garbage, not decrypt to somebody
else's key. Flowise's `crypto-js` CBC with no tag has none of this, which is
why `docs/flowise-notes.md` section 4 calls it the anti-pattern.

Two layers, deliberately. The primitive tests pin `encrypt_fields` /
`decrypt_fields` on bytes; the store tests then re-label a REAL row with a SQL
`UPDATE`, because the database's own integrity is exactly what the associated
data is there to make irrelevant, and a test that never touched a row would
be arguing about it.

No network, no model. The master key is a fresh random one per test, never
the environment's.
"""

from __future__ import annotations

import base64
import secrets
import unittest

from sqlalchemy import update

from brief_crew import config
from brief_crew.service.credentials import (
    CURRENT_KEY_VERSION,
    KEY_BYTES,
    NONCE_BYTES,
    CredentialNotYours,
    CredentialStore,
    CredentialTooLarge,
    CredentialUndecryptable,
    MasterKey,
    MasterKeyInvalid,
    ResolvedCredential,
    VaultUnavailable,
    associated_data,
    decrypt_fields,
    encrypt_fields,
    load_master_key,
    parse_master_key,
)
from brief_crew.service.persistence import PostgresFlowPersistence, user_credentials

FIELDS = {"api_key": "sk-or-v1-PLAINTEXT-THAT-MUST-NEVER-SURFACE"}
PLAINTEXT = FIELDS["api_key"]


def fresh_key() -> MasterKey:
    return MasterKey(secrets.token_bytes(KEY_BYTES))


class MasterKeyParsingTests(unittest.TestCase):
    def test_base64_of_32_bytes_round_trips(self) -> None:
        raw = secrets.token_bytes(KEY_BYTES)
        key = parse_master_key(base64.b64encode(raw).decode())
        self.assertEqual(key.version, CURRENT_KEY_VERSION)
        self.assertEqual(key.versions, (CURRENT_KEY_VERSION,))

    def test_not_base64_is_refused_naming_the_knob_and_the_mint_command(self) -> None:
        with self.assertRaises(MasterKeyInvalid) as caught:
            parse_master_key("this is not base64!!")
        self.assertIn("CREDENTIALS_MASTER_KEY", str(caught.exception))
        self.assertIn("secrets.token_bytes(32)", str(caught.exception))

    def test_the_wrong_length_is_refused_naming_the_length(self) -> None:
        with self.assertRaises(MasterKeyInvalid) as caught:
            parse_master_key(base64.b64encode(secrets.token_bytes(16)).decode())
        self.assertIn("16 bytes", str(caught.exception))

    def test_an_empty_or_blank_knob_is_no_vault_rather_than_an_error(self) -> None:
        self.assertIsNone(load_master_key(""))
        self.assertIsNone(load_master_key("   "))

    def test_the_repr_never_shows_the_bytes(self) -> None:
        raw = secrets.token_bytes(KEY_BYTES)
        rendered = repr(MasterKey(raw))
        self.assertNotIn(base64.b64encode(raw).decode(), rendered)
        self.assertNotIn(raw.hex(), rendered)
        self.assertIn("versions", rendered)

    def test_a_key_of_the_wrong_size_cannot_be_constructed(self) -> None:
        with self.assertRaises(MasterKeyInvalid):
            MasterKey(b"short")


class CipherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key = fresh_key()
        self.sealed = encrypt_fields(self.key, credential_id="cr_0000aaaa", user_id="alice", fields=FIELDS)

    def _open(self, *, credential_id: str = "cr_0000aaaa", user_id: str = "alice", **overrides: object) -> dict[str, str]:
        arguments = {
            "credential_id": credential_id,
            "user_id": user_id,
            "ciphertext": self.sealed.ciphertext,
            "nonce": self.sealed.nonce,
            "key_version": self.sealed.key_version,
        }
        arguments.update(overrides)
        return decrypt_fields(overrides.pop("key", None) or self.key, **arguments)  # type: ignore[arg-type]

    def test_the_owner_under_the_right_id_reads_the_fields_back(self) -> None:
        self.assertEqual(self._open(), FIELDS)

    def test_the_plaintext_is_not_in_the_ciphertext(self) -> None:
        self.assertNotIn(PLAINTEXT.encode(), self.sealed.ciphertext)
        self.assertEqual(len(self.sealed.nonce), NONCE_BYTES)
        self.assertEqual(self.sealed.key_version, CURRENT_KEY_VERSION)

    def test_relabelled_under_another_user_it_fails_to_authenticate(self) -> None:
        with self.assertRaises(CredentialUndecryptable) as caught:
            self._open(user_id="mallory")
        self.assertNotIn(PLAINTEXT, str(caught.exception))

    def test_relabelled_under_another_id_it_fails_to_authenticate(self) -> None:
        with self.assertRaises(CredentialUndecryptable):
            self._open(credential_id="cr_0000bbbb")

    def test_a_wrong_master_key_fails_to_authenticate(self) -> None:
        with self.assertRaises(CredentialUndecryptable):
            decrypt_fields(
                fresh_key(),
                credential_id="cr_0000aaaa",
                user_id="alice",
                ciphertext=self.sealed.ciphertext,
                nonce=self.sealed.nonce,
                key_version=self.sealed.key_version,
            )

    def test_a_flipped_byte_fails_to_authenticate(self) -> None:
        tampered = bytearray(self.sealed.ciphertext)
        tampered[0] ^= 0x01
        with self.assertRaises(CredentialUndecryptable):
            self._open(ciphertext=bytes(tampered))

    def test_a_nonce_of_the_wrong_length_is_refused_before_the_cipher_sees_it(self) -> None:
        with self.assertRaises(CredentialUndecryptable) as caught:
            self._open(nonce=b"\x00" * 8)
        self.assertIn("8-byte nonce", str(caught.exception))

    def test_key_version_round_trips_and_an_unheld_version_is_named(self) -> None:
        self.assertEqual(self.sealed.key_version, self.key.version)
        newer = MasterKey(secrets.token_bytes(KEY_BYTES), version=2)
        with self.assertRaises(CredentialUndecryptable) as caught:
            decrypt_fields(
                newer,
                credential_id="cr_0000aaaa",
                user_id="alice",
                ciphertext=self.sealed.ciphertext,
                nonce=self.sealed.nonce,
                key_version=self.sealed.key_version,
            )
        self.assertIn("key version 1", str(caught.exception))
        self.assertIn("writes version 2", str(caught.exception))

    def test_the_nonce_is_never_reused_across_ten_thousand_writes(self) -> None:
        nonces = {
            encrypt_fields(self.key, credential_id="cr_0000aaaa", user_id="alice", fields=FIELDS).nonce
            for _ in range(10_000)
        }
        self.assertEqual(len(nonces), 10_000)
        self.assertTrue(all(len(nonce) == NONCE_BYTES for nonce in nonces))

    def test_the_same_fields_seal_differently_every_time(self) -> None:
        again = encrypt_fields(self.key, credential_id="cr_0000aaaa", user_id="alice", fields=FIELDS)
        self.assertNotEqual(again.ciphertext, self.sealed.ciphertext)

    def test_over_the_byte_ceiling_is_refused_before_anything_is_sealed(self) -> None:
        with self.assertRaises(CredentialTooLarge) as caught:
            encrypt_fields(
                self.key,
                credential_id="cr_0000aaaa",
                user_id="alice",
                fields={"api_key": "k" * (config.MAX_CREDENTIAL_BYTES + 1)},
            )
        self.assertIn(str(config.MAX_CREDENTIAL_BYTES), str(caught.exception))

    def test_the_associated_data_is_unambiguous(self) -> None:
        # `cr_1` + `2x` and `cr_12` + `x` concatenate to the same string; the
        # NUL separator is what keeps them two different bindings.
        self.assertNotEqual(associated_data("cr_1", "2x"), associated_data("cr_12", "x"))

    def test_a_resolved_credential_hides_its_fields_from_repr_and_str(self) -> None:
        resolved = ResolvedCredential(kind="openrouter", fields=FIELDS)
        self.assertNotIn(PLAINTEXT, repr(resolved))
        self.assertNotIn(PLAINTEXT, str(resolved))
        self.assertIn("***", repr(resolved))
        self.assertEqual(resolved.fields["api_key"], PLAINTEXT)


class StoreTests(unittest.TestCase):
    """The same properties on a real row, over the service's own store."""

    def setUp(self) -> None:
        self.persistence = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.persistence.close)
        self.store = CredentialStore(self.persistence, master_key=fresh_key())

    def test_create_then_resolve_reads_the_fields_and_moves_last_used_at(self) -> None:
        created = self.store.create("alice", kind="openrouter", label="k", fields=FIELDS)
        self.assertIsNone(self.store.get("alice", created.id).last_used_at)

        resolved = self.store.resolve("alice", created.id)

        self.assertEqual(resolved.kind, "openrouter")
        self.assertEqual(dict(resolved.fields), FIELDS)
        self.assertIsNotNone(self.store.get("alice", created.id).last_used_at)

    def test_a_row_relabelled_in_sql_stops_decrypting_for_anybody(self) -> None:
        created = self.store.create("alice", kind="openrouter", label="k", fields=FIELDS)
        with self.persistence.begin() as connection:
            connection.execute(
                update(user_credentials)
                .where(user_credentials.c.id == created.id)
                .values(user_id="mallory")
            )
        # The row is now, by the database's account, Mallory's - and the tag
        # says otherwise. Not `CredentialNotYours`: the row was FOUND.
        with self.assertRaises(CredentialUndecryptable) as caught:
            self.store.resolve("mallory", created.id)
        self.assertNotIn(PLAINTEXT, str(caught.exception))
        # And it is no longer Alice's row to find.
        with self.assertRaises(CredentialNotYours):
            self.store.resolve("alice", created.id)

    def test_a_store_written_under_one_key_does_not_open_under_another(self) -> None:
        created = self.store.create("alice", kind="openrouter", label="k", fields=FIELDS)
        rotated = CredentialStore(self.persistence, master_key=fresh_key())
        with self.assertRaises(CredentialUndecryptable):
            rotated.resolve("alice", created.id)

    def test_an_unconfigured_store_refuses_to_seal_or_open_and_can_still_list(self) -> None:
        keyless = CredentialStore(self.persistence, master_key=None)
        self.assertFalse(keyless.configured)
        with self.assertRaises(VaultUnavailable):
            keyless.create("alice", kind="openrouter", label="k", fields=FIELDS)
        self.assertEqual(keyless.list("alice"), [])

    def test_exists_answers_only_for_the_owner(self) -> None:
        created = self.store.create("alice", kind="openrouter", label="k", fields=FIELDS)
        self.assertTrue(self.store.exists("alice", created.id))
        self.assertFalse(self.store.exists("bob", created.id))
        self.assertFalse(self.store.exists(None, created.id))
        self.assertFalse(self.store.exists("alice", "cr_00000000"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
