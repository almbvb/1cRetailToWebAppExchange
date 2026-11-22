"""Тесты приёма из 1С. Тестовые учётные данные и GUID — только для тестов (в .env их нет)."""

import uuid

TEST_BASIC_USER = "test_exchange"
# Не ASCII намеренно: сравнение идёт по байтам UTF-8.
TEST_BASIC_PASSWORD = "test-pass-Пароль-42"
TEST_BASIC = (TEST_BASIC_USER, TEST_BASIC_PASSWORD)
TEST_BEARER_TOKEN = "test-bearer-token-0123456789"
# ONEC_STORE_ID в тестах и «чужой» магазин.
TEST_STORE_ID = uuid.UUID("5b0f1c2e-1111-4a2b-9c3d-000000000001")
OTHER_STORE_ID = uuid.UUID("5b0f1c2e-2222-4a2b-9c3d-000000000002")
