# -*- coding: utf-8 -*-
import pytest
from mock import Mock

from ansible.module_utils.basic import AnsibleModule

from manageiq_client.api import ManageIQClient
import manageiq_custom_attributes


MANAGEIQ_HOSTNAME = "http://miq.example.com"
PROVIDER_NAME = "openshift01"
PROVIDER_HOSTNAME = "os01.example.com"
PROVIDER_ID = 266
EXISTING_CA = {"id": 6226, "name": "ca1", "value": "value 1"}
NEW_CA = {"id": 6227, "name": "ca2", "value": "value 2"}
UPDATED_CA_VALUE = "new value"
DEFAULT_SECTION = "metadata"
DIFFERENT_SECTION = 'section'
PROVIDER_URL = "{host}/api/providers/{id}".format(host=MANAGEIQ_HOSTNAME, id=PROVIDER_ID)


def provider_ca(section, name, value, id=None, href=False):
    """Builds a custom attribute hash for provider PROVIDER_ID."""
    ca = {
        "resource_id": PROVIDER_ID,
        "resource_type": "ExtManagementSystem",
        "section": section,
        "name": name,
        "value": value,
        "serialized_value": value,
        "source": "EVM",
    }
    if id is not None:
        ca["id"] = id
    if href:
        assert id is not None
        ca["href"] = "{provider}/custom_attributes/{ca_id}".format(provider=PROVIDER_URL, ca_id=id)
    return ca

GET_RETURN_VALUES = {
    'no_cas': {},
    'ca_exist': {
        "custom_attributes": [
            provider_ca(DEFAULT_SECTION, EXISTING_CA['name'], EXISTING_CA['value'], id=EXISTING_CA['id'], href=True),
        ]
    }
}
POST_RETURN_VALUES = {
    'added_ca': {
        'results': [
            provider_ca(DEFAULT_SECTION, NEW_CA['name'], NEW_CA['value'], id=NEW_CA['id']),
        ]
    },
    'added_ca_with_section': {
        'results': [
            provider_ca(DIFFERENT_SECTION, NEW_CA['name'], UPDATED_CA_VALUE, id=NEW_CA['id']),
        ]
    },
    'updated_ca': {
        'results': [
            provider_ca(DEFAULT_SECTION, EXISTING_CA['name'], UPDATED_CA_VALUE, id=EXISTING_CA['id']),
        ]
    }
}


@pytest.fixture(autouse=True)
def miq_api_class(monkeypatch):
    miq_api_class = Mock(spec=ManageIQClient)
    monkeypatch.setattr("manageiq_custom_attributes.MiqApi", miq_api_class)
    yield miq_api_class


@pytest.fixture
def the_provider():
    the_provider = Mock()
    the_provider.name = PROVIDER_NAME
    yield the_provider


@pytest.fixture
def miq_ansible_module():
    miq_ansible_module = Mock(spec=AnsibleModule)
    yield miq_ansible_module


class AnsibleModuleFailed(Exception):
    pass


@pytest.fixture()
def miq(miq_api_class, miq_ansible_module, the_provider):

    def fail(msg):
        raise AnsibleModuleFailed(msg)

    miq_ansible_module.fail_json = fail
    miq = manageiq_custom_attributes.ManageIQCustomAttributes(
        miq_ansible_module, MANAGEIQ_HOSTNAME, "The username", "The password",
        verify_ssl=False, ca_bundle_path=None)

    miq_api_class.return_value.collections.providers = [the_provider]

    yield miq


def test_get_entity_custom_attributes(miq, miq_api_class):
    miq_api_class.return_value.get.return_value = GET_RETURN_VALUES['ca_exist']
    provider_cas = miq.get_entity_custom_attributes('provider', PROVIDER_ID)
    miq_api_class.return_value.get.assert_called_with(
        "{provider}?expand=custom_attributes".format(provider=PROVIDER_URL, ca_id=id))
    assert provider_cas == GET_RETURN_VALUES['ca_exist']['custom_attributes']


def test_add_custom_attributes_if_none_exist(miq, miq_api_class):
    miq_api_class.return_value.get.return_value = GET_RETURN_VALUES['no_cas']
    miq_api_class.return_value.post.return_value = POST_RETURN_VALUES['added_ca']

    new_ca = [{'name': NEW_CA['name'], 'value': NEW_CA['value'], 'section': DEFAULT_SECTION}]
    result = miq.add_or_update_custom_attributes('provider', PROVIDER_NAME, new_ca)
    assert result == {
        'changed': True,
        'msg': "Successfully set the custom attributes to {entity_name} {entity_type}".format(entity_name=PROVIDER_NAME, entity_type='provider'),
        'updates': {
            'Added': POST_RETURN_VALUES['added_ca']['results'],
            'Updated': []
        }
    }


def test_update_existing_custom_attribute(miq, miq_api_class):
    miq_api_class.return_value.get.return_value = GET_RETURN_VALUES['ca_exist']
    miq_api_class.return_value.post.return_value = POST_RETURN_VALUES['updated_ca']

    updated_ca = [{'name': EXISTING_CA['name'], 'value': UPDATED_CA_VALUE, 'section': DEFAULT_SECTION}]
    result = miq.add_or_update_custom_attributes('provider', PROVIDER_NAME, updated_ca)
    miq_api_class.return_value.post.assert_called_once_with(
        "{provider}?expand=custom_attributes".format(provider=PROVIDER_URL, ca_id=id))
    assert result == {
        'changed': True,
        'msg': "Successfully set the custom attributes to {entity_name} {entity_type}".format(entity_name=PROVIDER_NAME, entity_type='provider'),
        'updates': {
            'Added': [],
            'Updated': POST_RETURN_VALUES['updated_ca']['results']
        }
    }


def test_compare_custom_attribute_with_section(miq, miq_api_class):
    """
    This test makes sure that if a custom attribute with the same name but
    different section to an existing custom attribute is to be present then
    it will be added and not update the existing custom attribute.
    """
    miq_api_class.return_value.get.return_value = GET_RETURN_VALUES['ca_exist']
    miq_api_class.return_value.post.return_value = POST_RETURN_VALUES['added_ca_with_section']

    updated_ca = [{'name': EXISTING_CA['name'], 'value': UPDATED_CA_VALUE, 'section': DIFFERENT_SECTION}]
    result = miq.add_or_update_custom_attributes('provider', PROVIDER_NAME, updated_ca)
    assert result == {
        'changed': True,
        'msg': "Successfully set the custom attributes to {entity_name} {entity_type}".format(entity_name=PROVIDER_NAME, entity_type='provider'),
        'updates': {
            'Added': POST_RETURN_VALUES['added_ca_with_section']['results'],
            'Updated': [],
        }
    }


def delete_existing_custom_attribute(miq, miq_api_class):
    miq_api_class.return_value.get.return_value = GET_RETURN_VALUES['ca_exist']
    miq_api_class.return_value.post.return_value = POST_RETURN_VALUES['added_ca']

    deleted_ca = [{'name': EXISTING_CA['name'], 'value': EXISTING_CA['value']}]
    result = miq.delete_custom_attributes('provider', PROVIDER_NAME, deleted_ca)
    assert result == {
        'changed': True,
        'msg': "Successfully deleted the following custom attributes from {provider_name} provider: {deleted}".format(
            provider_name=PROVIDER_NAME, deleted=POST_RETURN_VALUES['added_ca']['results'])
    }
