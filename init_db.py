"""
Script pour initialiser la base de données
Usage: python init_db.py
"""
import asyncio
import asyncpg
from app.core.config import settings
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_database():
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    logger.info("🔌 Connexion à la base de données...")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        schema_path = Path("app/db/schema.sql")
        logger.info(f"📋 Lecture du schéma depuis: {schema_path}")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = f.read()
        
        logger.info("📋 Exécution du schéma SQL...")
        await conn.execute(schema)
        
        logger.info("✅ Base de données initialisée avec succès!")
        
    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        raise
    finally:
        if 'conn' in locals():
            await conn.close()

if __name__ == "__main__":
    asyncio.run(init_database())
