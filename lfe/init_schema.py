"""Explicitly install the constraints needed for LFE graph uploads."""
import argparse

from .config import neo4j_environment
from .neo4j_repo import ConfigurationError, DatabaseOperationError, Neo4jRepository


def main():
    parser = argparse.ArgumentParser(description="Install LFE uniqueness constraints.")
    parser.add_argument("--env-dev", action="store_true", help="Load settings from .env_dev in the current directory.")
    parser.add_argument("--confirm-database", required=True, help="Name of the configured database to modify.")
    args = parser.parse_args()
    try:
        repository = Neo4jRepository(neo4j_environment(use_env_dev=args.env_dev))
        if repository.database != args.confirm_database:
            parser.exit(2, "The confirmed database does not match the configured database; no changes made.\n")
        repository.create_constraints()
    except (ValueError, RuntimeError, ConfigurationError, DatabaseOperationError) as exc:
        parser.exit(2, f"{exc}\n")
    print("LFE graph constraints installed and verified.")


if __name__ == "__main__":
    main()
