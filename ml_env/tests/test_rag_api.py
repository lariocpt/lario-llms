"""CPU-only ASGI contract tests; all storage, mapper, embedding and LLM calls are fake."""
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(os.environ.get('RAG_API_SCRIPTS', str(Path(__file__).resolve().parents[1] / 'scripts')))
sys.path.insert(0, str(SCRIPTS))
import httpx
from chromadb.errors import NotFoundError

with patch.dict(os.environ, {}, clear=True):
    rag = importlib.import_module('rag_api')

HTTP_CLIENT = httpx.AsyncClient
TOKEN = 'synthetic-test-key'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
COLLECTIONS = '/chroma/api/v2/tenants/default_tenant/databases/default_database/collections'


class RAGTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.environment = patch.dict(os.environ, {
            'KB_BACKEND_TOKEN': TOKEN, 'KB_MAPPING_URL': 'http://mapper.test',
            'HTTP_PROXY': 'http://untrusted-proxy.test:8080',
        }, clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.calls = []
        self.mapping_status = 200
        self.mapping = {'scope': 'kb-buddha', 'generation': 'test-generation',
                        'results': [{'document': 'published test evidence', 'metadata': {'source': 'test.md'}, 'distance': .1}]}
        self.mapping_unavailable = False
        self.vectors = [[1.0] + [0.0] * 1023]
        self.collection = Mock()
        self.collection.query.return_value = {
            'documents': [['legacy test evidence']], 'metadatas': [[{'source': 'old-test.md'}]], 'distances': [[.2]]}
        self.chroma = Mock()
        self.chroma.get_collection.return_value = self.collection
        self.old_chroma, self.old_embed = rag.chroma_client, rag.embed_client
        rag.chroma_client = self.chroma
        self.embed = HTTP_CLIENT(base_url='http://embedding.test', transport=httpx.MockTransport(self.outbound))
        rag.embed_client = self.embed
        self.client = HTTP_CLIENT(base_url='http://rag.test', transport=httpx.ASGITransport(app=rag.app))
        self.outbound_options = []
        def client_factory(**kwargs):
            self.outbound_options.append(kwargs)
            return HTTP_CLIENT(transport=httpx.MockTransport(self.outbound), **kwargs)
        self.http_patch = patch.object(rag.httpx, 'AsyncClient', side_effect=client_factory)
        self.http_patch.start(); self.addCleanup(self.http_patch.stop)
        self.llm_patch = patch.object(rag, 'LLM_API', 'http://llm.test/v1')
        self.llm_patch.start(); self.addCleanup(self.llm_patch.stop)

    async def asyncTearDown(self):
        await self.client.aclose(); await self.embed.aclose()
        rag.chroma_client, rag.embed_client = self.old_chroma, self.old_embed

    def outbound(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.host, request.url.path, body))
        if request.url.host == 'mapper.test':
            if self.mapping_unavailable: raise httpx.ConnectError('offline', request=request)
            if isinstance(self.mapping, bytes):
                return httpx.Response(self.mapping_status, content=self.mapping)
            return httpx.Response(self.mapping_status, json=self.mapping)
        if request.url.host == 'embedding.test':
            return httpx.Response(200, json={'embeddings': self.vectors})
        if request.url.host == 'llm.test':
            return httpx.Response(200, json={'choices': [{'message': {'content': 'test answer'}}]})
        if request.url.host == 'chromadb':
            return httpx.Response(200, json=1 if request.url.path.endswith('/count') else {'id': 'test-id'})
        raise AssertionError('Unexpected outbound request')

    async def retrieve(self, collection='kb-buddha', headers=None, **fields):
        return await self.client.post('/retrieve', json={'collection': collection, 'query': 'test query', 'top_k': 1, **fields}, headers=headers)

    async def test_public_shared_retrieval_uses_verified_generation_only(self):
        response = await self.retrieve()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.mapping)
        self.chroma.get_collection.assert_not_called()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.outbound_options[0]['trust_env'])

    async def test_only_explicit_unpublished_scope_permits_legacy_fallback(self):
        self.mapping_status = 404
        self.mapping = {'error': 'scope has no active generation', 'legacy_allowed': True}
        response = await self.retrieve()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['generation'], 'legacy')
        self.chroma.get_collection.assert_called_once_with('kb-buddha')
        self.chroma.create_collection.assert_not_called()

    async def test_mapper_errors_never_fall_back_to_old_evidence(self):
        for status, body in ((404, {'error': 'not found'}), (404, {'legacy_allowed': 'true'}),
                             (500, {}), (503, {'legacy_allowed': True}), (200, b'not JSON'),
                             (200, []), (200, {'results': []}),
                             (200, {**self.mapping, 'scope': 'another-scope'})):
            with self.subTest(status=status, body=body):
                self.mapping_status, self.mapping = status, body
                response = await self.retrieve()
                self.assertEqual(response.status_code, 503)
        self.chroma.get_collection.assert_not_called()

    async def test_mapper_outage_or_missing_config_fails_closed(self):
        self.mapping_unavailable = True
        self.assertEqual((await self.retrieve()).status_code, 503)
        os.environ['KB_MAPPING_URL'] = ''
        self.assertEqual((await self.retrieve()).status_code, 503)
        self.chroma.get_collection.assert_not_called()

    async def test_public_cannot_read_private_or_physical_collections(self):
        for collection in ('private-user', 'coder_private_test', 'kbpub_test', [], {}, None):
            with self.subTest(collection=collection):
                self.assertEqual((await self.retrieve(collection)).status_code, 403)
        self.assertEqual(self.calls, [])
        self.chroma.get_collection.assert_not_called()

    async def test_public_cannot_embed_ingest_or_use_storage_proxy(self):
        for path, body in (('/embed', {'texts': ['test']}), ('/ingest', {'documents': ['test']}),
                           (COLLECTIONS, {'name': 'test'})):
            self.assertEqual((await self.client.post(path, json=body)).status_code, 403)
        self.assertEqual((await self.client.get(COLLECTIONS)).status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_unicode_or_missing_secret_never_authorizes(self):
        response = await self.client.post('/embed', json={'texts': ['test']},
                                          headers={b'authorization': b'Bearer \xff'})
        self.assertEqual(response.status_code, 403)
        os.environ['KB_BACKEND_TOKEN'] = ''
        self.assertEqual((await self.client.post('/embed', json={'texts': ['test']}, headers=AUTH)).status_code, 403)

    async def test_trusted_raw_retrieval_skips_mapper_and_never_creates(self):
        response = await self.retrieve('coder_private_test', headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.chroma.get_collection.assert_called_once_with('coder_private_test')
        self.chroma.create_collection.assert_not_called()
        self.assertTrue(all(host != 'mapper.test' for _, host, _, _ in self.calls))

    async def test_missing_collection_and_storage_outage_are_distinct(self):
        for error, status in ((NotFoundError('absent'), 404), (RuntimeError('offline'), 503)):
            self.chroma.get_collection.side_effect = error
            self.assertEqual((await self.retrieve('coder_private_test', headers=AUTH)).status_code, status)
        self.chroma.create_collection.assert_not_called()

    async def test_bge_m3_model_and_dimensions_remain_fixed(self):
        response = await self.client.post('/embed', json={'texts': ['test'], 'model': 'BAAI/bge-m3'}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['embeddings'][0]), 1024)
        self.assertEqual(self.calls[-1][3], {'texts': ['test'], 'normalize': True, 'model': 'BAAI/bge-m3'})
        self.assertEqual((await self.client.post('/embed', json={'texts': ['test'], 'model': 'another-model'}, headers=AUTH)).status_code, 400)
        self.vectors = [[0.] * 384]
        self.assertEqual((await self.client.post('/embed', json={'texts': ['test']}, headers=AUTH)).status_code, 502)

    async def test_trusted_ingest_embeds_before_adding_documents(self):
        response = await self.client.post('/ingest', json={'collection': 'test', 'documents': ['test'], 'ids': ['id']}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.collection.add.call_args.kwargs['embeddings'], self.vectors)

    async def test_ingest_creates_only_a_missing_collection(self):
        self.chroma.get_collection.side_effect = NotFoundError('absent')
        self.chroma.create_collection.return_value = self.collection
        response = await self.client.post('/ingest', json={'collection': 'test', 'documents': ['test']}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.chroma.create_collection.assert_called_once_with('test')

    async def test_ingest_storage_outage_never_attempts_collection_creation(self):
        self.chroma.get_collection.side_effect = RuntimeError('offline')
        response = await self.client.post('/ingest', json={'collection': 'test', 'documents': ['test']}, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.chroma.create_collection.assert_not_called()
        self.assertEqual(self.calls, [])

    async def test_query_uses_mapped_evidence_and_rejects_other_embedding_models(self):
        response = await self.client.post('/query', json={'collection': 'kb-buddha', 'query': 'test query', 'top_k': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['context_used'], ['published test evidence'])
        self.assertEqual(response.json()['generation'], 'test-generation')
        self.assertEqual(response.json()['scope'], 'kb-buddha')
        self.assertIn('published test evidence', self.calls[-1][3]['messages'][0]['content'])
        self.calls.clear()
        response = await self.client.post('/query', json={'collection': 'kb-buddha', 'query': 'test query', 'model': 'another-model'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.calls, [])

    async def test_storage_proxy_has_exact_method_and_operation_allowlist(self):
        for method, path in (('GET', COLLECTIONS), ('POST', COLLECTIONS),
                             ('GET', COLLECTIONS + '/test-id/count'), ('POST', COLLECTIONS + '/test-id/add')):
            response = await self.client.request(method, path, json={} if method == 'POST' else None, headers=AUTH)
            self.assertEqual(response.status_code, 200)
        for method, path in (('POST', COLLECTIONS + '/test-id/count'), ('GET', COLLECTIONS + '/test-id/add'),
                             ('POST', COLLECTIONS + '/test-id/delete'), ('POST', COLLECTIONS + '/test-id/upsert'),
                             ('POST', COLLECTIONS + '/test-id/query')):
            with self.subTest(method=method, path=path):
                self.assertEqual((await self.client.request(method, path, json={} if method == 'POST' else None, headers=AUTH)).status_code, 403)
        self.assertTrue(all(option['trust_env'] is False for option in self.outbound_options))

    async def test_invalid_json_and_oversized_bodies_rejected_before_backends(self):
        self.assertEqual((await self.client.post('/retrieve', content=b'{')).status_code, 400)
        self.assertEqual((await self.client.post('/ingest', content=b'x' * 4_000_001, headers=AUTH)).status_code, 413)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    import logging
    logging.getLogger('httpx').setLevel(logging.WARNING)
    unittest.main()
