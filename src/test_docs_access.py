#!/usr/bin/env python
"""Test Swagger documentation without API key."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aniprovider_api.settings')
django.setup()

from django.test import Client

# Set API key to ensure it's required for other endpoints
os.environ['ANIPROVIDER_API_KEY'] = 'test-key-123'

# Re-import settings to pick up the env var
from django.conf import settings
settings.ANIPROVIDER_API_KEY = 'test-key-123'

c = Client()

# Test without API key
print("Testing WITHOUT API key header:")
r1 = c.get('/api/docs/')
print(f"  /api/docs/     → {r1.status_code} ✅" if r1.status_code == 200 else f"  /api/docs/     → {r1.status_code} ❌")

r2 = c.get('/api/redoc/')
print(f"  /api/redoc/    → {r2.status_code} ✅" if r2.status_code == 200 else f"  /api/redoc/    → {r2.status_code} ❌")

r3 = c.get('/api/schema/')
print(f"  /api/schema/   → {r3.status_code} ✅" if r3.status_code == 200 else f"  /api/schema/   → {r3.status_code} ❌")

# Test Business endpoint WITHOUT API key (should fail)
print("\nTesting Business endpoint WITHOUT API key (should be 401):")
r4 = c.get('/api/animes/test/episodes')
print(f"  /api/animes/.../episodes → {r4.status_code} {'✅ (correctly rejected)' if r4.status_code == 401 else '❌ (should be 401)'}")

# Test Business endpoint WITH API key (should pass)
print("\nTesting Business endpoint WITH API key (should be 200/500):")
r5 = c.get('/api/animes/test/episodes', HTTP_X_API_KEY='test-key-123')
print(f"  /api/animes/.../episodes → {r5.status_code} {'✅ (authorized)' if r5.status_code in [200, 400, 500] else '❌ (should be authorized)'}")
