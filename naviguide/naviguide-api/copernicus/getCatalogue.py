import copernicusmarine

print("✅ Copernicus Marine SDK version :", copernicusmarine.__version__)

# Test simple du catalogue
catalogue = copernicusmarine.describe(contains=["wind"])
print(f"Produits trouvés : {len(catalogue.products)}")
