"""
Script pour initialiser la base de données
Usage: python -m app.db.init_db
"""
import asyncio
import asyncpg
from app.core.config import settings
import logging
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_database_url(url: str) -> dict:
    """Parse l'URL PostgreSQL en paramètres de connexion"""
    # Nettoyer l'URL
    url = url.replace("postgresql://", "").replace("postgresql+asyncpg://", "")
    
    # Format: user:password@host:port/database
    if "@" in url:
        auth_part, host_part = url.split("@")
        user, password = auth_part.split(":")
        
        if "/" in host_part:
            host_port, database = host_part.split("/", 1)
            # Enlever les paramètres query si présents
            database = database.split("?")[0]
        else:
            host_port = host_part
            database = "postgres"
        
        if ":" in host_port:
            host, port = host_port.split(":")
        else:
            host = host_port
            port = "5432"
    else:
        raise ValueError("Format URL invalide")
    
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": int(port),
        "database": database
    }

async def init_database():
    logger.info("🔌 Connexion à la base de données...")
    
    try:
        # Parser l'URL manuellement
        conn_params = parse_database_url(settings.DATABASE_URL)
        
        logger.info(f"   Host: {conn_params['host']}")
        logger.info(f"   Database: {conn_params['database']}")
        
        # Connexion avec paramètres individuels
        conn = await asyncpg.connect(
            user=conn_params["user"],
            password=conn_params["password"],
            host=conn_params["host"],
            port=conn_params["port"],
            database=conn_params["database"]
        )
        
        try:
            # Lire le fichier schema.sql
            with open("app/db/schema.sql", "r", encoding="utf-8") as f:
                schema = f.read()
            
            logger.info("📋 Exécution du schéma SQL...")
            await conn.execute(schema)
            
            logger.info("✅ Base de données initialisée avec succès!")
            
        finally:
            await conn.close()
            
    except FileNotFoundError:
        logger.error("❌ Fichier schema.sql non trouvé. Assure-toi d'être dans le dossier backend/")
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(init_database())
