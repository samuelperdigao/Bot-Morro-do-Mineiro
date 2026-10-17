import unittest

from features.acao.service import acao_service as feature_acao_service
from features.set.service import set_request_service as feature_set_service
from infrastructure.repositories.acoes import acao_repository
from infrastructure.repositories.set_requests import set_request_repository
from services.acao_service import acao_service
from services.set_requests import set_request_service


class ArchitectureLayerTests(unittest.TestCase):
    def test_feature_apis_preserve_the_existing_service_singletons(self):
        self.assertIs(feature_set_service, set_request_service)
        self.assertIs(feature_acao_service, acao_service)

    def test_repositories_expose_the_domain_persistence_operations(self):
        self.assertTrue(callable(set_request_repository.create))
        self.assertTrue(callable(set_request_repository.claim))
        self.assertTrue(callable(acao_repository.create))
        self.assertTrue(callable(acao_repository.finalize))


if __name__ == "__main__":
    unittest.main()
