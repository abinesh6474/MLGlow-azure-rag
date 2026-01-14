from typing import Optional

import glob
import csv
import json

from azure.core.credentials_async import AsyncTokenCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.models import VectorizedQuery 
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,  
    SimpleField,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration)
from azure.ai.inference.aio import EmbeddingsClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
from .util import ChatRequest


class SearchIndexManager:
    """
    The class for searching of context for user queries.

    :param endpoint: The search endpoint to be used.
    :param credential: The credential to be used for the search.
    :param index_name: The name of an index to get or to create.
    :param dimensions: The number of dimensions in the embedding. Set this parameter only if
                       embedding model accepts dimensions parameter.
    :param model: The embedding model to be used,
                  must be the same as one use to build the file with embeddings.
    :param embeddings_client: The embedding client.
    """
    
    MIN_DIFF_CHARACTERS_IN_LINE = 5
    MIN_LINE_LENGTH = 5
    
    def __init__(
            self,
            endpoint: str,
            credential: AsyncTokenCredential,
            index_name: str,
            dimensions: Optional[int],
            model: str,
            embeddings_client: EmbeddingsClient,
        ) -> None:
        """Constructor."""
        self._dimensions = dimensions
        self._index_name = index_name
        self._embeddings_client = embeddings_client
        self._endpoint = endpoint
        self._credential = credential
        self._index = None
        self._model = model
        self._client = None

    def _get_client(self):
        """Get search client if it is absent."""
        if self._client is None:
            self._client = SearchClient(
                endpoint=self._endpoint, index_name=self._index.name, credential=self._credential)
        return self._client

    async def search(self, message: ChatRequest) -> str:
        """
        Search the message in the vector store.

        :param message: The customer question.
        :return: The context for the question.
        """
        self._raise_if_no_index()
        embedded_question = (await self._embeddings_client.embed(
            input=message.messages[-1].content,
            dimensions=self._dimensions,
            model=self._model
        ))['data'][0]['embedding']
        vector_query = VectorizedQuery(vector=embedded_question, k_nearest_neighbors=5, fields="text_vector")
        response = await self._get_client().search(
            vector_queries=[vector_query],
            select=['chunk'],
        )
        results = [result['chunk'] async for result in response]
        return "\n------\n".join(results)
    
    async def upload_documents(self, embeddings_file: str) -> None:
        """
        Upload the embeggings file to index search.

        :param embeddings_file: The embeddings file to upload.
        """
        self._raise_if_no_index()
        documents = []
        index = 0
        with open(embeddings_file, newline='') as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                documents.append(
                    {
                        'embedId': str(index),
                        'token': row['token'],
                        'embedding': json.loads(row['embedding'])
                    }
                )
                index += 1
        await self._get_client().upload_documents(documents)

    async def is_index_empty(self) -> bool:
        """
        Return True if the index is empty.

        :return: True f index is empty.
        """
        if self._index is None:
            raise ValueError(
                "Unable to perform the operation as the index is absent. "
                "To create index please call create_index")
        document_count = await self._get_client().get_document_count()
        return document_count == 0

    def _raise_if_no_index(self) -> None:
        """
        Raise the exception if the index was not created.

        :raises: ValueError
        """
        if self._index is None:
            raise ValueError(
                "Unable to perform the operation as the index is absent. "
                "To create index please call create_index")

    async def delete_index(self):
        """Delete the index from vector store."""
        self._raise_if_no_index()
        async with SearchIndexClient(endpoint=self._endpoint, credential=self._credential) as ix_client:
            await ix_client.delete_index(self._index.name)
        self._index = None

    def _check_dimensions(self, vector_index_dimensions: Optional[int] = None) -> int:
        """
        Check that the dimensions are set correctly.

        :return: the correct vector index dimensions.
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them set and they do not equal each other.
        """
        if vector_index_dimensions is None:
            if self._dimensions is None:
                raise ValueError(
                    "No embedding dimensions were provided in neither dimensions in the constructor nor in vector_index_dimensions"
                    "Dimensions are needed to build the search index, please provide the vector_index_dimensions.")
            vector_index_dimensions = self._dimensions
        if self._dimensions is not None and vector_index_dimensions != self._dimensions:
            raise ValueError("vector_index_dimensions is different from dimensions provided to constructor.")
        return vector_index_dimensions

    async def ensure_index_created(self, vector_index_dimensions: Optional[int] = None) -> None:
        """
        Get the search index. Create the index if it does not exist.

        :param vector_index_dimensions: The number of dimensions in the vector index. This parameter is
               needed if the embedding parameter cannot be set for the given model. It can be
               figured out by loading the embeddings file, generated by build_embeddings_file,
               loading the contents of the first row and 'embedding' column as a JSON and calculating
               the length of the list obtained.
               Also please see the embedding model documentation
               https://platform.openai.com/docs/models#embeddings
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them set and they do not equal each other.
        """
        vector_index_dimensions = self._check_dimensions(vector_index_dimensions)
        if self._index is None:
            self._index = await SearchIndexManager.get_or_create_index(
                self._endpoint,
                self._credential,
                self._index_name,
                vector_index_dimensions)

    @staticmethod
    async def index_exists(
        endpoint: str,
        credential: AsyncTokenCredential,
        index_name: str) -> bool:
        """
        Check if index exists.

        :param endpoint: The search end point to be used.
        :param credential: The credential to be used for the search.
        :param index_name: The name of an index to get or to create.
        :return: True if index already exists.
        """
        exists = False
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            try:
                await ix_client.get_index(index_name)
                exists = True
            except ResourceNotFoundError:
                pass
        return exists

    @staticmethod
    async def get_or_create_index(
            endpoint: str,
            credential: AsyncTokenCredential,
            index_name: str,
            dimensions: int,
        ) -> SearchIndex:
        """
        Get o create the search index.

        **Note:** If the search index with index_name exists, the embeddings_file will not be uploaded.
        :param endpoint: The search end point to be used.
        :param credential: The credential to be used for the search.
        :param index_name: The name of an index to get or to create.
        :param dimensions: The number of dimensions in the embedding.
        :return: the search index object.
        """
        index = None
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            try:
                index = await ix_client.get_index(index_name)
            except ResourceNotFoundError:
                pass
        if index is None:
            index = await SearchIndexManager._index_create(
                endpoint=endpoint,
                credential=credential,
                index_name=index_name,
                dimensions=dimensions
            )
        return index

    async def create_index(
        self,
        vector_index_dimensions: Optional[int] = None) -> bool:
        """
        Create index or return false if it already exists.

        :param vector_index_dimensions: The number of dimensions in the vector index. This parameter is
               needed if the embedding parameter cannot be set for the given model. It can be
               figured out by loading the embeddings file, generated by build_embeddings_file,
               loading the contents of the first row and 'embedding' column as a JSON and calculating
               the length of the list obtained.
               Also please see the embedding model documentation
               https://platform.openai.com/docs/models#embeddings
        :return: True if index was created, False otherwise.
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them are set and they do not equal each other.
        """
        vector_index_dimensions = self._check_dimensions(vector_index_dimensions)
        try:
            self._index = await SearchIndexManager._index_create(
                endpoint=self._endpoint,
                credential=self._credential,
                index_name=self._index_name,
                dimensions=vector_index_dimensions
            )
            return True
        except HttpResponseError:
            return False
        

    @staticmethod
    async def _index_create(
        endpoint: str,
        credential: AsyncTokenCredential,
        index_name: str,
        dimensions: int) -> SearchIndex:
        """Create the index."""
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            fields = [
                SimpleField(name="embedId", type=SearchFieldDataType.String, key=True),
                SearchField(
                    name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    vector_search_dimensions=dimensions,
                    searchable=True,
                    vector_search_profile_name="embedding_config"
                ),
                SimpleField(name="token", type=SearchFieldDataType.String, hidden=False),
            ]
            vector_search = VectorSearch(
                profiles=[VectorSearchProfile(name="embedding_config",
                                              algorithm_configuration_name="embed-algorithms-config")],
                algorithms=[HnswAlgorithmConfiguration(name="embed-algorithms-config")],
            )
            search_index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
            new_index = await ix_client.create_index(search_index)
        return new_index
        

async def build_embeddings_file(
        self,
        input_directory: str,
        output_file: str,
        sentences_per_embedding: int = 4,
        include_subdirs: bool = False ## new parameter (sub_dirs)
) -> None:
    """
    Build embeddings from markdown (.md) or JSON files.
    
    Supports multiple JSON formats:
    - Multi-chunk recipes (recipe_id, chunk_type)
    - Nine Favorite Things (content, meta_json_string)
    - Essentials (multiple recipes in one file)
    - Weekly Meal Plan (meal plan by day)
    
    :param input_directory: The directory with .md or .json files.
    :param output_file: The CSV file to store embeddings.
    :param sentences_per_embedding: The number of sentences used to build embedding.
    """
    import nltk
    try:
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)
    except:
        pass

    from nltk.tokenize import sent_tokenize

    sentence_tokens = []

    # Process both .md and .json files
    # conditional glob pattern based on flag
    if include_subdirs:
        # search subdirectories recursively
        md_pattern = input_directory + '/**/*.md'
        json_pattern = input_directory + '/**/*.json'
        print(f"Searching directories and all subdirectories: {input_directory}")
    else:
        # Search only top level directory
        md_pattern = input_directory + '/*.md'
        json_pattern = input_directory + '/*.json'
        print(f"Searching only top level directory: {input_directory}")

    md_files = glob.glob(md_pattern, recursive=include_subdirs)
    json_files = glob.glob(json_pattern, recursive=include_subdirs)
    
    all_files = md_files + json_files

    if not all_files:
        raise ValueError(f"No .md or .json files found in directory: {input_directory}")
    
    print(f"Found {len(md_files)} markdown files and {len(json_files)} JSON files.")

    stats = {
        'recipes': 0,
        'favorites': 0,
        'essentials': 0,
        'meal_plans': 0,
        'other': 0
    }
    index = 0

    # Process Mardown files
    for fle in md_files:
        with open(fle, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if len(line) < SearchIndexManager.MIN_LINE_LENGTH or len(set(line)) < SearchIndexManager.MIN_DIFF_CHARACTERS_IN_LINE:
                    continue
                for sentence in sent_tokenize(line):
                    if index % sentences_per_embedding ==0:
                        sentence_tokens.append(sentence)
                    else:
                        sentence_tokens[-1] += ' '
                        sentence_tokens[-1] += sentence
                    index += 1

    # Process JSON files
    for file_num, fle in enumerate(json_files, 1):
        if file_num % 100 == 0:
            print(f"Processed {file_num}/{len(json_files)} JSON files...")

        try:
            with open(fle, encoding='utf-8') as f:
                data = json.load(f)

            # Determine file type and process accordingly
            file_type = self._detect_json_file_type(data)

            if file_type == 'multi_chunk_recipes':
                # Format 1: Multi-chunk recipes
                stats['recipes'] += self._process_multi_chunk_recipes(data, sentence_tokens, sentences_per_embedding, sent_tokenize, index)

            elif file_type == 'nine_favorites':
                # Format 2: Nine Favorite Things
                stats['favorites'] += 1
                self._process_favorites(data, sentence_tokens, sentences_per_embedding, sent_tokenize, index)

            elif file_type == 'essentials':
                # Format 3: Essentials
                stats['essentials'] += 1
                self._process_essentials(data, sentence_tokens, sentences_per_embedding, sent_tokenize, index)

            elif file_type == 'meal_plan':
                # Format 4: Weekly Meal Plan
                stats['meal_plans'] += 1
                self._process_meal_plan(data, sentence_tokens, sentences_per_embedding, sent_tokenize, index)

            else:
                stats['other'] += 1
                self._process_generic_json(data, sentence_tokens, sentences_per_embedding, sent_tokenize, index)

        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse {fle}: {e}")
            continue
        except Exception as e:
            print(f"Warning: Error processing {fle}: {e}")
            continue
    
    if not sentence_tokens:
        raise ValueError("No content extracted from files.")
    
    print(f"\nProcessing Summary:")
    print(f" - Recipes: {stats['recipes']}")
    print(f" - Nine Favorites: {stats['favorites']}")
    print(f" - Essentials: {stats['essentials']}")
    print(f" - Meal Plans: {stats['meal_plans']}")
    print(f" - Other: {stats['other']}")
    print(f" Total chunks: {len(sentence_tokens)}")

    # Build embeddings in batches
    batch_size = 2000
    with open(output_file, 'w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=['token', 'embedding'])
        writer.writeheader()

        total_batches = (len(sentence_tokens) + batch_size -1) // batch_size
        for batch_num, i in enumerate(range(0, len(sentence_tokens), batch_size), 1):
            print(f"Creating embeddings batch {batch_num}/{total_batches}...")
            batch_tokens = sentence_tokens[i:i+min(batch_size, len(sentence_tokens)-i)]

            embedding = (await self._embeddings_client.embed(
                input=batch_tokens,
                dimensions=self._dimensions,
                model=self._model  
            ))["data"]

            for token, float_data in zip(batch_tokens, embedding):
                writer.writerow({'token': token, 'embedding': json.dumps(float_data['embedding'])})
        
        print(f"\n Embeddings saved to {output_file}")

def _detect_json_type(self, data):
    """Detect which JSON format we're dealing with."""
    if isinstance(data, list) and len(data) > 0:
        first_item = data[0]
        if isinstance(first_item, dict):
            # Multi-chunk recipes have recipe_id and chunk_type
            if 'recipe_id' in first_item and 'chunk_type' in first_item:
                return 'multi_chunk_recipes'
    
    if isinstance(data, dict):
        # Nine Favorites and others have 'content' and 'meta_json_string'
        if 'content' in data and 'meta_json_string' in data:
            try:
                meta = json.loads(data['meta_json_string'])
                section_type = meta.get('section_type', '')
                
                if section_type == 'nine_favorite_things':
                    return 'nine_favorites'
                elif section_type == 'essentials':
                    return 'essentials'
                elif section_type == 'weekly_meal_plan':
                    return 'meal_plan'
            except:
                pass
    
    return 'unknown'

def _process_multi_chunk_recipes(self, data, sentence_tokens, sentences_per_embedding, sent_tokenize, index):
    """Process multi-chunk recipe format."""
    recipes_by_id = {}
    
    for item in data:
        if isinstance(item, dict):
            recipe_id = item.get('recipe_id', item.get('id', 'unknown'))
            if recipe_id not in recipes_by_id:
                recipes_by_id[recipe_id] = []
            recipes_by_id[recipe_id].append(item)
    
    for recipe_id, chunks in recipes_by_id.items():
        chunks.sort(key=lambda x: x.get('order', 0))
        recipe_text = ""
        
        for chunk in chunks:
            chunk_type = chunk.get('chunk_type', '')
            chunk_content = chunk.get('chunk', '')
            
            if chunk_type == 'title':
                recipe_text += f"Recipe: {chunk_content}. "
            elif chunk_type in ['short_description', 'full_description']:
                recipe_text += f"{chunk_content} "
            elif chunk_type == 'ingredients':
                ingredients = chunk_content.replace('Ingredients : ', '')
                recipe_text += f"Ingredients: {ingredients}. "
            elif chunk_type == 'instructions':
                recipe_text += f"Instructions: {chunk_content} "
            elif chunk_type == 'notes':
                recipe_text += f"Notes: {chunk_content} "
            
            # Add metadata
            if 'meta' in chunk and chunk['meta']:
                meta = chunk['meta']
                if meta.get('prep_time'):
                    recipe_text += f"Prep time: {meta['prep_time']}. "
                if meta.get('cook_time'):
                    recipe_text += f"Cook time: {meta['cook_time']}. "
                if meta.get('servings'):
                    recipe_text += f"Serves: {meta['servings']}. "
                if meta.get('cuisine'):
                    recipe_text += f"Cuisine: {meta['cuisine']}. "
                if meta.get('course'):
                    recipe_text += f"Course: {meta['course']}. "
            
            if 'categories' in chunk and chunk['categories']:
                categories = ', '.join(chunk['categories']) if isinstance(chunk['categories'], list) else chunk['categories']
                recipe_text += f"Categories: {categories}. "
            
            if 'keywords' in chunk and chunk['keywords']:
                keywords = ', '.join(chunk['keywords']) if isinstance(chunk['keywords'], list) else chunk['keywords']
                recipe_text += f"Keywords: {keywords}. "
        
        # Tokenize
        recipe_text = recipe_text.strip()
        if recipe_text:
            sentences = sent_tokenize(recipe_text)
            for sentence in sentences:
                if len(sentence) >= SearchIndexManager.MIN_LINE_LENGTH:
                    if index % sentences_per_embedding == 0:
                        sentence_tokens.append(sentence)
                    else:
                        sentence_tokens[-1] += ' '
                        sentence_tokens[-1] += sentence
                    index += 1
    
    return len(recipes_by_id)

def _process_favorites(self, data, sentence_tokens, sentences_per_embedding, sent_tokenize, index):
    """Process Nine Favorite Things format."""
    content = data.get('content', '')
    
    # Parse metadata
    try:
        meta = json.loads(data.get('meta_json_string', '{}'))
        title = meta.get('title', 'Nine Favorite Things')
        author = meta.get('Author', '')
        published = meta.get('published_date', '')
        
        text = f"{title}. "
        if author:
            text += f"By {author}. "
        if published:
            text += f"Published: {published}. "
        text += content
    except:
        text = content
    
    # Tokenize
    if text:
        sentences = sent_tokenize(text)
        for sentence in sentences:
            if len(sentence) >= SearchIndexManager.MIN_LINE_LENGTH:
                if index % sentences_per_embedding == 0:
                    sentence_tokens.append(sentence)
                else:
                    sentence_tokens[-1] += ' '
                    sentence_tokens[-1] += sentence
                index += 1

def _process_essentials(self, data, sentence_tokens, sentences_per_embedding, sent_tokenize, index):
    """Process Essentials format (multiple recipes in one file)."""
    content = data.get('content', '')
    
    # Parse metadata for context
    try:
        meta = json.loads(data.get('meta_json_string', '{}'))
        section_type = meta.get('section_type', 'Essentials')
        
        # Extract title/description from content
        lines = content.split('\n')
        processed_text = f"Essential Recipes: {section_type}. {content}"
    except:
        processed_text = content
    
    # Tokenize
    if processed_text:
        sentences = sent_tokenize(processed_text)
        for sentence in sentences:
            if len(sentence) >= SearchIndexManager.MIN_LINE_LENGTH:
                if index % sentences_per_embedding == 0:
                    sentence_tokens.append(sentence)
                else:
                    sentence_tokens[-1] += ' '
                    sentence_tokens[-1] += sentence
                index += 1

def _process_meal_plan(self, data, sentence_tokens, sentences_per_embedding, sent_tokenize, index):
    """Process Weekly Meal Plan format."""
    content = data.get('content', '')
    
    # Parse metadata
    try:
        meta = json.loads(data.get('meta_json_string', '{}'))
        date = meta.get('date', '')
        
        text = f"Weekly Meal Plan for {date}. {content}"
    except:
        text = content
    
    # Tokenize
    if text:
        sentences = sent_tokenize(text)
        for sentence in sentences:
            if len(sentence) >= SearchIndexManager.MIN_LINE_LENGTH:
                if index % sentences_per_embedding == 0:
                    sentence_tokens.append(sentence)
                else:
                    sentence_tokens[-1] += ' '
                    sentence_tokens[-1] += sentence
                index += 1

def _process_generic_json(self, data, sentence_tokens, sentences_per_embedding, sent_tokenize, index):
    """Fallback for unknown JSON formats."""
    text_content = ""
    
    if isinstance(data, dict):
        for key in ['title', 'name', 'content', 'text', 'description']:
            if key in data:
                text_content += str(data[key]) + " "
    elif isinstance(data, str):
        text_content = data
    
    if text_content:
        sentences = sent_tokenize(text_content)
        for sentence in sentences:
            if len(sentence) >= SearchIndexManager.MIN_LINE_LENGTH:
                if index % sentences_per_embedding == 0:
                    sentence_tokens.append(sentence)
                else:
                    sentence_tokens[-1] += ' '
                    sentence_tokens[-1] += sentence
                index += 1

    async def close(self):
        """Close the closeable resources, associated with SearchIndexManager."""
        if self._client:
            await self._client.close()
