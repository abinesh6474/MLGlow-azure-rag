
"""
Build embeddings from your recipe files (JSON or Markdown).

Usage:
    python build_embeddings.py --input-dir src/api/data --output src/api/data/embeddings.csv
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from azure.ai.projects.aio import AIProjectClient
from azure.identity import AzureDeveloperCliCredential
from azure.core.credentials import AzureKeyCredential

from api.search_index_manager import SearchIndexManager


async def main_build(
    input_directory: str,
    output_file: str,
    sentences_per_embedding: int = 4,
    dimensions: int = None,
    include_subdirs: bool = False  ## new line (sub_dirs)
):
    """Build embeddings from documents."""
    # Load .env from src/ directory
    env_path = Path(__file__).parent.parent / 'src' / '.env'
    load_dotenv(env_path)
    
    print("="*70)
    print("Building Custom Embeddings from Your Recipe Files")
    print("="*70)
    print(f" Input directory: {input_directory}")
    print(f" Output file: {output_file}")
    print(f" Sentences per embedding: {sentences_per_embedding}")
    print(f" Include subdirectories: {'Yes' if include_subdirs else 'No'}") ## new line (sub_dirs)
    
    if dimensions is None:
        dimensions = int(os.getenv('AZURE_AI_EMBED_DIMENSIONS', '100'))
    print(f" Dimensions: {dimensions}")
    print("="*70 + "\n")
    
    # Authenticate
    if os.getenv("AZURE_EXISTING_AIPROJECT_API_KEY"):
        print(" Using API Key authentication")
        azure_credential = AzureKeyCredential(os.environ["AZURE_EXISTING_AIPROJECT_API_KEY"])
        azure_search_credential = AzureKeyCredential(os.environ["AZURE_AI_SEARCH_API_KEY"])
    else:
        print(" Using Azure Developer CLI authentication")
        if tenant_id := os.getenv("AZURE_TENANT_ID"):
            azure_credential = AzureDeveloperCliCredential(tenant_id=tenant_id)
        else:
            azure_credential = AzureDeveloperCliCredential()
        azure_search_credential = azure_credential
    
    # Initialize clients
    project = AIProjectClient(
        credential=azure_credential,
        endpoint=os.environ["AZURE_EXISTING_AIPROJECT_ENDPOINT"]
    )
    
    embedding_client = project.inference.get_embeddings_client()
    
    # Create SearchIndexManager
    search_index_manager = SearchIndexManager(
        endpoint=os.environ['AZURE_AI_SEARCH_ENDPOINT'],
        credential=azure_search_credential,
        index_name=os.environ['AZURE_AI_SEARCH_INDEX_NAME'],
        dimensions=dimensions,
        model=os.environ['AZURE_AI_EMBED_DEPLOYMENT_NAME'],
        embeddings_client=embedding_client,
    )
    
    try:
        print(" Processing documents and creating embeddings...")
        print(" This may take a few minutes...\n")
        
        # Build embeddings
        await search_index_manager.build_embeddings_file(
            input_directory=input_directory,
            output_file=output_file,
            sentences_per_embedding=sentences_per_embedding,
            include_subdirs=include_subdirs  ## new line (sub_dirs)
        )
        
        print(f"\n SUCCESS! Embeddings file created: {output_file}\n")
        
        # Ask to upload
        upload_now = input(" Upload embeddings to Azure Search Index now? (y/n): ")
        
        if upload_now.lower() == 'y':
            print("\n Ensuring Azure Search Index exists...")
            await search_index_manager.ensure_index_created(
                vector_index_dimensions=dimensions
            )
            print(" Index ready!")
            
            print("\n Uploading documents to index...")
            await search_index_manager.upload_documents(output_file)
            
            print(f" Upload complete! Index: {os.environ['AZURE_AI_SEARCH_INDEX_NAME']}\n")
        else:
            print("\n  Skipped upload. You can upload later.\n")
            
    except FileNotFoundError as e:
        print(f"\n ERROR: Directory not found: {input_directory}")
        print(f" Create it: mkdir {input_directory}\n")
        raise
    except Exception as e:
        print(f"\n ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        raise
    finally:
        print(" Cleaning up resources...")
        await search_index_manager.close()
        await project.close()
        await embedding_client.close()
        print(" Done!\n")


def main():
    parser = argparse.ArgumentParser(
        description='Build embeddings from recipe files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using default paths
  python scripts/build_embeddings.py --input-dir src/api/data --output src/api/data/embeddings.csv
  
  # With custom sentences per embedding
  python scripts/build_embeddings.py --input-dir src/api/data --output src/api/data/embeddings.csv --sentences 6
        """
    )
    
    parser.add_argument(
        '--input-dir', 
        type=str, 
        default='src/api/data',
        help='Directory with recipe files (default: src/api/data)'
    )
    parser.add_argument(
        '--output', 
        type=str, 
        default='src/api/data/embeddings.csv',
        help='Output CSV file (default: src/api/data/embeddings.csv)'
    )
    parser.add_argument(
        '--sentences', 
        type=int, 
        default=4,
        help='Sentences per embedding (default: 4)'
    )
    parser.add_argument(
        '--dimensions', 
        type=int, 
        default=None,
        help='Embedding dimensions (default: from .env)'
    )

    parser.add_argument(
    '--include-subdirs',
    action='store_true',
    help='Include subdirectories when searching for files'
    )
    
    args = parser.parse_args()
    
    # Validate input
    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f" ERROR: Directory not found: {args.input_dir}")
        print(f" Create it: mkdir {args.input_dir}")
        return 1
    
    # Check for files
    json_files = list(input_path.glob('*.json'))
    md_files = list(input_path.glob('*.md'))
    
    if not json_files and not md_files:
        print(f"  WARNING: No .json or .md files in {args.input_dir}")
        proceed = input("Continue anyway? (y/n): ")
        if proceed.lower() != 'y':
            return 0
    else:
        print(f" Found {len(json_files)} JSON and {len(md_files)} Markdown files\n")
    
    # Create output directory
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    
    # Run
    try:
        asyncio.run(main_build(
            input_directory=args.input_dir,
            output_file=args.output,
            sentences_per_embedding=args.sentences,
            dimensions=args.dimensions,
            include_subdirs=args.include_subdirs  ## new line (sub_dirs)
        ))
        return 0
    except KeyboardInterrupt:
        print("\n\n Cancelled by user\n")
        return 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())