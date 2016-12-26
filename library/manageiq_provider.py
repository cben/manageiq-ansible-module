#!/usr/bin/python

import os
import time
from ansible.module_utils.basic import *
from manageiq_client.api import ManageIQClient as MiqApi


DOCUMENTATION = '''
---
module: manageiq_provider
short_description: add, update, delete provider in ManageIQ
requirements: [ ManageIQ/manageiq-api-client-python ]
author: Daniel Korn (@dkorn)
options:
  miq_url:
    description:
      - the manageiq environment url
    default: MIQ_URL env var if set. otherwise, it is required to pass it
  miq_username:
    description:
      - manageiq username
    default: MIQ_USERNAME env var if set. otherwise, it is required to pass it
  miq_password:
    description:
      - manageiq password
    default: MIQ_PASSWORD env var if set. otherwise, it is required to pass it
  verify_ssl:
    description:
      - whether SSL certificates should be verified for HTTPS requests
    required: false
    default: True
    choices: ['True', 'False']
  ca_bundle_path:
    description:
      - the path to a CA_BUNDLE file or directory with certificates
    required: false
    default: null
  name:
    description:
      - the added provider name in manageiq
    required: true
    default: null
  provider_type:
    description:
      - the provider's type
    required: true
    choices: ['openshift-origin', 'openshift-enterprise', 'amazon']
  state:
    description:
      - the state of the provider
      - On present, it will add the provider if it does not exist or update the
      provider if the associated data is different
      - On absent, it will delete the provider if it exists
    required: false
    choices: ['present', 'absent']
    default: 'present'
  zone:
    description:
      - the provider zone name in manageiq
    required: false
    default: null
  provider_api_hostname:
    description:
      - the provider API hostname
    required: true
    default: null
  provider_api_port:
    description:
      - the port used by the provider API
    required: true
    default: null
  provider_api_auth_token:
    description:
      - the provider api auth token
    required: true
    default: null
  metrics:
    description:
      - whether metrics should be enabled in the provider
    required: false
    default: False
    choices: ['True', 'False']
  hawkular_hostname:
    description:
      - the hostname used for hawkular metrics
    required: false
    default: null
  hawkular_port:
    description:
      - the port used for hawkular metrics
    required: false
    default: null
'''

EXAMPLES = '''
# Add Openshift Containers Provider to ManageIQ
  manageiq_provider:
    name: 'Molecule'
    provider_type: 'openshift-enterprise'
    state: 'present'
    miq_url: 'http://miq.example.com'
    miq_username: 'admin'
    miq_password: '******'
    zone: 'default'
    provider_api_hostname: 'oshift01.redhat.com'
    provider_api_port: '8443'
    provider_api_auth_token: '******'
    verify_ssl: False
    metrics: True
    hawkular_hostname: 'hawkular01.redhat.com'
    hawkular_port: '443'

# Remove Openshift Provider from HTTPS ManageIQ environment
  manageiq_provider:
    name: 'OS01'
    provider_type: 'openshift-enterprise'
    state: 'absent'
    miq_url: 'https://miq.example.com'
    miq_username: 'admin'
    miq_password: '******'
    verify_ssl: True
    ca_bundle_path: '/path/to/certfile'
    provider_api_hostname: 'oshift01.redhat.com'
    provider_api_port: '8443'
    provider_api_auth_token: '******'

# Add Amazon EC2 Cloud provider to ManageIQ
  manageiq_provider:
    name: 'AWS01'
    provider_type: 'amazon'
    provider_region: 'us-west-2"
    access_key_id: '******'
    secret_access_key: '******'
    state: 'present'
    verify_ssl: False
    miq_url: 'http://localhost:3000'
    miq_username: 'admin'
    miq_password: '******'
'''


class ManageIQ(object):
    """ ManageIQ object to execute various operations in manageiq

    url            - manageiq environment url
    user           - the username in manageiq
    password       - the user password in manageiq
    verify_ssl     - whether SSL certificates should be verified for HTTPS requests
    ca_bundle_path - the path to a CA_BUNDLE file or directory with certificates
    """

    OPENSHIFT_DEFAULT_PORT = '8443'

    PROVIDER_TYPES = {
        'openshift-origin': 'ManageIQ::Providers::Openshift::ContainerManager',
        'openshift-enterprise': 'ManageIQ::Providers::OpenshiftEnterprise::ContainerManager',
        'amazon': 'ManageIQ::Providers::Amazon::CloudManager'}

    WAIT_TIME = 5
    ITERATIONS = 10

    def __init__(self, module, url, user, password, verify_ssl, ca_bundle_path):
        self.module        = module
        self.api_url       = url + '/api'
        self.user          = user
        self.password      = password
        self.client        = MiqApi(self.api_url, (self.user, self.password), verify_ssl=verify_ssl, ca_bundle_path=ca_bundle_path)
        self.changed       = False
        self.providers_url = self.api_url + '/providers'

    def auths_validation_details(self, provider_id):
        try:
            result = self.client.get('{providers_url}/{id}/?attributes=authentications'.format(providers_url=self.providers_url, id=provider_id))
            auths = result.get('authentications', [])
            return {auth['authtype']: auth for auth in auths}
        except Exception as e:
            self.module.fail_json(msg="Failed to get provider data. Error: %s" % e)

    def verify_authenticaion_validation(self, provider_id, old_validation_details, authtypes_to_verify):
        """ Verifies that the provider's authentication validation passed.
        provider_id            - the provider's id manageiq
        old_validation_details - a tuple of (last_valid_on, last_invalid_on), representing the last time
                                 that the authentication validation occured (success or failure).
        authtypes_to_verify    - a list of autentication types that require validation

        Returns a (success, details) tuple:
            success: True if authentication validation passed, False otherwise
            details: 'All Valid' if passed, authentication validation details otherwise
        """
        for i in range(ManageIQ.ITERATIONS):
            new_validation_details = self.auths_validation_details(provider_id)

            def validated(old, new):
                """ Returns True if the validation timestamp, valid or invalid, is different
                from the old validation timestamp, False otherwise
                """
                return ((old.get('last_valid_on'), old.get('last_invalid_on')) !=
                        (new.get('last_valid_on'), new.get('last_invalid_on')))

            validations_done = all(validated(old_validation_details.get(t, {}), new_validation_details.get(t, {}))
                                   for t in authtypes_to_verify)
            details = {t: (new_validation_details[t].get('status', "Validation in progress"),
                           new_validation_details[t].get('status_details', ''))
                       for t in authtypes_to_verify}
            if validations_done:
                if any(new_validation_details[t]['status'] not in ('Valid', None) for t in authtypes_to_verify):
                    return False, details
                if all(new_validation_details[t]['status'] == 'Valid' for t in authtypes_to_verify):
                    return True, 'All Valid'
            time.sleep(ManageIQ.WAIT_TIME)
        return False, details

    def required_updates(self, provider_id, endpoints, zone_id, provider_region):
        """ Checks whether an update is required for the provider

        Returns:
            Empty Hash (None) - If the hostname, port, zone and region passed equals
                                the provider's current values
            Hash of Changes   - Changes that need to be made if any endpoint, zone
                                or region are different than the current values of the
                                provider. The hash will have three entries:
                                    Updated, Removed, Added
                                that will contain all the changed endpoints
                                and their values.
        """
        try:
            result = self.client.get('{providers_url}/{id}/?attributes=endpoints'.format(providers_url=self.providers_url, id=provider_id))
        except Exception as e:
            self.module.fail_json(msg="Failed to get provider data. Error: {!r}".format(e))

        def host_port(endpoint):
            return {'hostname': endpoint.get('hostname'), 'port': endpoint.get('port')}

        desired_by_role = {e['endpoint']['role']: host_port(e['endpoint']) for e in endpoints}
        result_by_role = {e['role']: host_port(e) for e in result['endpoints']}
        existing_provider_region = result.get('provider_region') or None
        if result_by_role == desired_by_role and result['zone_id'] == zone_id and existing_provider_region == provider_region:
            return {}
        updated = {role: {k: v for k, v in ep.items()
                          if k not in result_by_role[role] or v != result_by_role[role][k]}
                   for role, ep in desired_by_role.items()
                   if role in result_by_role and ep != result_by_role[role]}
        added = {role: ep for role, ep in desired_by_role.items()
                 if role not in result_by_role}
        removed = {role: ep for role, ep in result_by_role.items()
                   if role not in desired_by_role}
        if result['zone_id'] != zone_id:
            updated['zone_id'] = zone_id
        if existing_provider_region != provider_region:
            updated['provider_region'] = provider_region
        return {"Updated": updated, "Added": added, "Removed": removed}

    def update_provider(self, provider_id, provider_name, endpoints, zone_id, provider_region):
        """ Updates the existing provider with new parameters
        """
        try:
            self.client.post('{api_url}/providers/{id}'.format(api_url=self.api_url, id=provider_id),
                             action='edit',
                             zone={'id': zone_id},
                             connection_configurations=endpoints,
                             provider_region=provider_region)
            self.changed = True
        except Exception as e:
            self.module.fail_json(msg="Failed to update provider. Error: {!r}".format(e))

    def add_new_provider(self, provider_name, provider_type, endpoints, zone_id, provider_region):
        """ Adds a provider to manageiq

        Returns:
            the added provider id
        """
        try:
            result = self.client.post(self.providers_url, name=provider_name,
                                      type=ManageIQ.PROVIDER_TYPES[provider_type],
                                      zone={'id': zone_id},
                                      connection_configurations=endpoints,
                                      provider_region=provider_region)
            provider_id = result['results'][0]['id']
            self.changed = True
        except Exception as e:
            self.module.fail_json(msg="Failed to add provider. Error: {!r}".format(e))
        return provider_id

    def find_zone_by_name(self, zone_name):
        """ Searches the zone name in manageiq existing zones

        Returns:
            the zone id if it exists in manageiq, None otherwise
        """
        zones = self.client.collections.zones
        return next((z.id for z in zones if z.name == zone_name), None)

    def find_provider_by_name(self, provider_name):
        """ Searches the provider name in manageiq existing providers

        Returns:
            the provider id if it exists in manageiq, None otherwise
        """
        providers = self.client.collections.providers
        return next((p.id for p in providers if p.name == provider_name), None)

    def generate_openshift_endpoint(self, role, authtype, hostname, port, token):
        """ Returns an openshift provider endpoint dictionary.
        """
        return {'endpoint': {'role': role, 'hostname': hostname,
                             'port': int(port)},
                'authentication': {'authtype': authtype, 'auth_key': token}}

    def generate_amazon_endpoint(self, role, authtype, userid, password):
        """ Returns an amazon provider endpoint dictionary.
        """
        return {'endpoint': {'role': role},
                'authentication': {'authtype': authtype, 'userid': userid,
                                   'password': password}}

    def delete_provider(self, provider_name):
        """ Deletes the provider

        Returns:
            the delete task id if a task was generated, whether or not
            a change took place and a short message describing the operation
            executed.
        """
        provider_id = self.find_provider_by_name(provider_name)
        if provider_id:
            try:
                url = '{providers_url}/{id}'.format(providers_url=self.providers_url, id=provider_id)
                result = self.client.post(url, action='delete')
                if result['success']:
                    self.changed = True
                    return dict(task_id=result['task_id'], changed=self.changed, msg=result['message'])
                else:
                    return dict(task_id=None, changed=self.changed, api_error=result, msg="Failed to delete {provider_name} provider".format(provider_name=provider_name))
            except Exception as e:
                self.module.fail_json(msg="Failed to delete {provider_name} provider. Error: {error!r}".format(provider_name=provider_name, error=e))
        else:
            return dict(task_id=None, changed=self.changed, msg="Provider {provider_name} doesn't exist".format(provider_name=provider_name))

    def add_or_update_provider(self, provider_name, provider_type, endpoints, zone, provider_region):
        """ Adds a provider to manageiq or update its attributes in case
        a provider with the same name already exists

        Returns:
            the added or updated provider id, whether or not a change took
            place and a short message describing the operation executed,
            including the authentication validation status
        """
        zone_id = self.find_zone_by_name(zone or 'default')
        # check if provider with the same name already exists
        provider_id = self.find_provider_by_name(provider_name)
        if provider_id:  # provider exists
            updates = self.required_updates(provider_id, endpoints, zone_id, provider_region)
            if not updates:
                return dict(changed=self.changed,
                            msg="Provider %s already exists" % provider_name)

            old_validation_details = self.auths_validation_details(provider_id)
            operation = "update"
            self.update_provider(provider_id, provider_name, endpoints, zone_id, provider_region)
            roles_with_changes = set(updates["Added"]) | set(updates["Updated"])
        else:  # provider doesn't exists, adding it to manageiq
            updates = None
            old_validation_details = {}
            operation = "addition"
            provider_id = self.add_new_provider(provider_name, provider_type,
                                                endpoints, zone_id, provider_region)
            roles_with_changes = [e['endpoint']['role'] for e in endpoints]

        authtypes_to_verify = []
        for e in endpoints:
            if e['endpoint']['role'] in roles_with_changes:
                authtypes_to_verify.append(e['authentication']['authtype'])
        success, details = self.verify_authenticaion_validation(provider_id, old_validation_details, authtypes_to_verify)

        if success:
            message = "Successful {operation} of {provider} provider. Authentication: {validation}".format(operation=operation, provider=provider_name, validation=details)
        else:
            message = "Failed to validate provider {provider} after {operation}. Authentication: {validation}".format(operation=operation, provider=provider_name, validation=details)
        return dict(
            provider_id=provider_id,
            changed=self.changed,
            msg=message,
            updates=updates
        )


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(required=True),
            zone=dict(required=False, type='str'),
            provider_type=dict(required=True,
                               choices=['openshift-origin', 'openshift-enterprise', 'amazon']),
            state=dict(default='present',
                       choices=['present', 'absent']),
            miq_url=dict(default=os.environ.get('MIQ_URL', None)),
            miq_username=dict(default=os.environ.get('MIQ_USERNAME', None)),
            miq_password=dict(default=os.environ.get('MIQ_PASSWORD', None)),
            provider_api_port=dict(default=ManageIQ.OPENSHIFT_DEFAULT_PORT,
                                   required=False),
            provider_api_hostname=dict(required=False),
            provider_api_auth_token=dict(required=False, no_log=True),
            verify_ssl=dict(require=False, type='bool', default=True),
            ca_bundle_path=dict(required=False, type='str', defualt=None),
            provider_region=dict(required=False, type='str'),
            access_key_id=dict(required=False, type='str', no_log=True),
            secret_access_key=dict(required=False, type='str', no_log=True),
            metrics=dict(required=False, type='bool', default=False),
            hawkular_hostname=dict(required=False),
            hawkular_port=dict(required=False)
        ),
        required_if=[
            ('provider_type', 'openshift-origin', ['provider_api_hostname', 'provider_api_port', 'provider_api_auth_token']),
            ('provider_type', 'openshift-enterprise', ['provider_api_hostname', 'provider_api_port', 'provider_api_auth_token']),
            ('metrics', True, ['hawkular_hostname', 'hawkular_port']),
            ('provider_type', 'amazon', ['access_key_id', 'secret_access_key', 'provider_region'])
        ],
    )

    for arg in ['miq_url', 'miq_username', 'miq_password']:
        if module.params[arg] in (None, ''):
            module.fail_json(msg="missing required argument: {}".format(arg))

    miq_url           = module.params['miq_url']
    miq_username      = module.params['miq_username']
    miq_password      = module.params['miq_password']
    verify_ssl        = module.params['verify_ssl']
    ca_bundle_path    = module.params['ca_bundle_path']
    provider_name     = module.params['name']
    provider_type     = module.params['provider_type']
    state             = module.params['state']
    zone              = module.params['zone']
    provider_region   = module.params['provider_region']
    access_key_id     = module.params['access_key_id']
    secret_access_key = module.params['secret_access_key']
    hostname          = module.params['provider_api_hostname']
    port              = module.params['provider_api_port']
    token             = module.params['provider_api_auth_token']
    h_hostname        = module.params['hawkular_hostname']
    h_port            = module.params['hawkular_port']

    manageiq = ManageIQ(module, miq_url, miq_username, miq_password, verify_ssl, ca_bundle_path)

    if state == 'present':
        if provider_type in ("openshift-enterprise", "openshift-origin"):
            endpoints = [manageiq.generate_openshift_endpoint('default', 'bearer', hostname, port, token)]
            if module.params['metrics']:
                endpoints.append(manageiq.generate_openshift_endpoint('hawkular', 'hawkular', h_hostname, h_port, token))
        elif provider_type == "amazon":
            endpoints = [manageiq.generate_amazon_endpoint('default', 'default', access_key_id, secret_access_key)]

        res_args = manageiq.add_or_update_provider(provider_name,
                                                   provider_type,
                                                   endpoints,
                                                   zone,
                                                   provider_region)
    elif state == 'absent':
        res_args = manageiq.delete_provider(provider_name)

    module.exit_json(**res_args)


if __name__ == "__main__":
    main()
