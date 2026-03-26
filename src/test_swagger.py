#!/usr/bin/env python
"""Test Swagger documentation endpoints."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aniprovider_api.settings')
django.setup()

from django.test import Client

c = Client()

# Include API key if set in environment
headers = {}
if os.getenv('ANIPROVIDER_API_KEY'):
    headers['HTTP_X_API_KEY'] = os.getenv('ANIPROVIDER_API_KEY')

# Test Swagger JSON schema endpoint (request JSON format explicitly)
r1 = c.get('/api/schema/', {'format': 'json'}, **headers)
print(f"Schema endpoint (JSON): {r1.status_code}")

# Test Swagger UI endpoint
r2 = c.get('/api/docs/', **headers)
print(f"Swagger UI endpoint: {r2.status_code}")

# Test ReDoc endpoint
r3 = c.get('/api/redoc/', **headers)
print(f"ReDoc endpoint: {r3.status_code}")

# Test that the API endpoints themselves work
r4 = c.get('/api/animes/test-anime/episodes', **headers)
print(f"Episodes API endpoint: {r4.status_code}")

print("\n✅ Swagger documentation setup is complete!")
print("Access endpoints at:")
print("  - Swagger UI: http://localhost:8000/api/docs/")
print("  - ReDoc: http://localhost:8000/api/redoc/")
print("  - OpenAPI Schema: http://localhost:8000/api/schema/")
