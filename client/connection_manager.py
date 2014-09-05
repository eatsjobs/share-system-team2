#!/usr/bin/env python
# -*- coding: utf-8 -*-

# API:
#
# files:
# - GET /files/ - ottiene la lista dei file sul server con relativi metadati necessari e/o md5
# - GET /files/<path> - scarica un file
# - POST /files/<path> - crea un file
# - PUT /files/<path> - modifica un file
# actions:
# - POST /actions/copy - parametri src, dest
# - POST /actions/delete - parametro path
# - POST /actions/move - parametri src, dest
# ---------
# shares:
# - POST /shares/<root_path>/<user> - crea (se necessario) lo share, e l’utente che “vede” la condivisione
# - DELETE /shares/<root_path> - elimina del tutto lo share
# - DELETE /shares/<root_path>/<user> - elimina l’utente dallo share

import requests
import json
import os
import logging


class ConnectionManager(object):
    EXCEPTIONS_CATCHED = (requests.HTTPError,
                          requests.exceptions.ConnectionError,
                          requests.exceptions.MissingSchema,
                        )

    def __init__(self, cfg, logging_level=logging.ERROR):
        self.load_cfg(cfg)

        self.logger = logging.getLogger("ConMng")
        self.logger.setLevel(level=logging_level)

        # create a file handler
        if not os.path.isdir('log'):
            os.makedirs('log')

        handler = logging.FileHandler('log/test_connection_manager.log')
        handler.setLevel(logging_level)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        # create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging_level)

        console_formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)

        self.logger.addHandler(console_handler)

    def load_cfg(self, cfg):
        """
        Load the configuration received from client_daemon
        :param cfg: Dictionary where is contained the configuration
        """
        self.cfg = cfg
        self.auth = (self.cfg.get('user', None), self.cfg.get('pass', None))

        # example of self.base_url = 'http://localhost:5000/API/V1/'
        self.base_url = ''.join([self.cfg['server_address'], self.cfg['api_suffix']])
        self.files_url = ''.join([self.base_url, 'files/'])
        self.actions_url = ''.join([self.base_url, 'actions/'])
        self.shares_url = ''.join([self.base_url, 'shares/'])
        self.users_url = ''.join([self.base_url, 'users/'])

    def dispatch_request(self, command, args=None):
        method_name = ''.join(['do_', command])
        try:
            return getattr(self, method_name)(args)
        except AttributeError:
            self._default(method_name)

    def do_register(self, data):
        """
        Send registration user request
        """
        req = {'password': data[1]}
        url = ''.join([self.users_url, data[0]])
        self.logger.info('do_register: URL: {} - DATA: {} '.format(url, data))

        try:
            r = requests.post(url, data=req)
            # i must check before raise_for_status to not destroy response
            if r.status_code == 403:
                return {'improvements': json.loads(r.text), 'successful': False}
            elif r.status_code == 409:
                return {'content': 'Error! User already existent!', 'successful': False}
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('do_register: URL: {} - EXCEPTION_CATCHED: {} '.format(url, e))
            return {'content': 'Error during registration:\n{}'.format(e), 'successful': False}
        else:
            return {'content': json.loads(r.text), 'successful': True}

    def do_activate(self, data):
        """
        Send activation user request
        """
        req = {'activation_code': data[1]}
        url = ''.join([self.users_url, data[0]])
        self.logger.info('do_activate: URL: {} - DATA: {} '.format(url, data))

        try:
            r = requests.put(url, data=req)
            if r.status_code == 404:
                return {'content': 'Error! Impossible to activate user! Unexistent user!', 'successful': False}
            elif r.status_code == 409:
                return {'content': 'Error! Impossible to activate user! User already activated!', 'successful': False}
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('do_activate: URL: {} - EXCEPTION_CATCHED: {} '.format(url, e))
        else:
            return {'content': json.loads(r.text), 'successful': True}
        return {'content': 'Error during activation:\n{}'.format(e), 'successful': False}

    def do_reqrecoverpass(self, data):
        """
        Ask server for reset current user password.
        """
        mail = data
        url = '{}{}/reset'.format(self.users_url, mail)
        try:
            r = requests.post(url)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('do_reqrecoverpass: URL: {} - EXCEPTION_CATCHED: {}'.format(url, e))
        else:
            return r.text

    def do_recoverpass(self, data):
        """
        Change current password using the code given by email.
        """
        mail, recoverpass_code, new_password = data
        url = '{}{}'.format(self.users_url, mail)
        try:
            r = requests.put(url,
                             data={'password': new_password,
                                   'recoverpass_code': recoverpass_code})
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('do_recoverpass: URL: {} - EXCEPTION_CATCHED: {}'.format(url, e))
        else:
            return r.text

    # files

    def do_download(self, data):
        url = ''.join([self.files_url, data['filepath']])
        self.logger.info('{}: URL: {} - DATA: {} '.format('do_download', url, data))
        try:
            r = requests.get(url, auth=self.auth)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_download', url, e))
        else:
            filepath = os.path.join(self.cfg['sharing_path'], data['filepath'])
            dirpath, filename = os.path.split(filepath)
            if not os.path.isdir(dirpath):
                # Create all missing directories
                os.makedirs(dirpath)
            with open(filepath, 'wb') as f:
                f.write(r.content)
            return True
        return False

    def do_upload(self, data):
        filepath = os.path.join(self.cfg['sharing_path'], data['filepath'])

        # se è minore di 4 mega normal upload
        if os.path.getsize(filepath) < self.cfg['chunk_upload_threshold']:
            self._do_upload(data)
        else:
            self.do_mega_upload(data)

    def _do_upload(self, data):
        url = ''.join([self.files_url, data['filepath']])
        filepath = os.path.join(self.cfg['sharing_path'], data['filepath'])

        self.logger.info('{}: URL: {} - DATA: {} '.format('_do_upload', url, data))
        _file = {'file': (open(filepath, 'rb'))}

        try:
            r = requests.post(url, auth=self.auth, files=_file, data={'md5': data['md5']})
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_upload', url, e))
        else:
            event_timestamp = json.loads(r.text)
            return event_timestamp
        return False

    def do_mega_upload(self, data):
        chunk_size = 1048576 # 1MB
        filepath = os.path.join(self.cfg['sharing_path'], data['filepath'])
        size_of_file = os.path.getsize(filepath) # size of file in byte
        url = ''.join([self.files_url, data['filepath']])

        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                offset = f.tell()
                try:
                    r = requests.post(url, auth=self.auth, data={'md5': data['md5'], 'chunk': chunk, 'offset': offset})
                    r.raise_for_status()
                    if r.status_code == 201:
                        # upload of file completed 201
                        return True
                    elif r.status_code == 200:
                        # chunk completed 200
                        print (100 * offset) / size_of_file, "% Uploaded"
                except ConnectionManager.EXCEPTIONS_CATCHED as e:
                    # f.seek(0)
                    print e
                    break


    def do_modify(self, data):
        filepath = os.path.join(self.cfg['sharing_path'], data['filepath'])
        url = ''.join([self.files_url, data['filepath']])

        self.logger.info('{}: URL: {} - DATA: {} '.format('do_modify', url, data))

        _file = {'file': (open(filepath, 'rb'))}
        try:
            r = requests.put(url, auth=self.auth, files=_file, data={'md5': data['md5']})
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_modify', url, e))
        else:
            event_timestamp = json.loads(r.text)

            return event_timestamp
        return False

    # actions:

    def do_move(self, data):
        url = ''.join([self.actions_url, 'move'])
        d = {'src': data['src'], 'dst': data['dst']}
        self.logger.info('{}: URL: {} - DATA: {} '.format('do_move', url, data))
        try:
            r = requests.post(url, auth=self.auth, data=d)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_move', url, e))
        else:
            event_timestamp = json.loads(r.text)

            return event_timestamp
        return False

    def do_delete(self, data):
        url = ''.join([self.actions_url, 'delete'])
        self.logger.info('{}: URL: {} - DATA: {} '.format('do_delete', url, data))
        d = {'filepath': data['filepath']}
        try:
            r = requests.post(url, auth=self.auth, data=d)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_delete', url, e))
        else:
            event_timestamp = json.loads(r.text)
            return event_timestamp
        return False

    def do_copy(self, data):
        url = ''.join([self.actions_url, 'copy'])
        d = {'src': data['src'], 'dst': data['dst']}
        self.logger.info('{}: URL: {} - DATA: {} '.format('do_copy', url, data))
        try:
            r = requests.post(url, auth=self.auth, data=d)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:
            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_copy', url, e))
        else:
            event_timestamp = json.loads(r.text)

            return event_timestamp
        return False

    def do_get_server_snapshot(self, data):
        url = self.files_url

        self.logger.info('{}: URL: {} - DATA: {} '.format('do_get_server_snapshot', url, data))

        try:
            r = requests.get(url, auth=self.auth)
            r.raise_for_status()
        except ConnectionManager.EXCEPTIONS_CATCHED as e:

            self.logger.error('{}: URL: {} - EXCEPTION_CATCHED: {} '.format('do_get_server_snapshot', url, e))

        else:
            return json.loads(r.text)

    def _default(self, method):
        print 'Received Unknown Command:', method