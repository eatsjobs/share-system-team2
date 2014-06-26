#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
server test module

Every TestCase class should use the <TEST_DIR> directory. To do it, just call 'setup_test_dir()' in the setUp method and
'tear_down_test_dir()' in the tearDown one.
"""
import unittest
import io
import os
import base64
import shutil
import urlparse
import json
import logging

import server
from server import userpath2serverpath

start_dir = os.getcwd()

TEST_DIR = 'server_test'

SERVER_API = '/API/V1/'
SERVER_FILES_API = urlparse.urljoin(SERVER_API, 'files/')
SERVER_ACTIONS_API = urlparse.urljoin(SERVER_API, 'actions/')

# Set server logging verbosity
server_verbosity = logging.WARNING  # change it manually if you want change the server verbosity
server.logger.setLevel(server_verbosity)
# Very basic logging configuration for this test module:
logging.basicConfig(level=logging.WARNING)

# Test-user account details
REGISTERED_TEST_USER = 'pyboxtestuser', 'pw'
USR, PW = REGISTERED_TEST_USER


def _create_file(username, user_relpath, content, update_userdata=True):
    """
    Create an user file with path <user_relpath> and content <content>
    and return it's last modification time (== creation time).
    :param username: str
    :param user_relpath: str
    :param content: str
    :return: float
    """
    filepath = userpath2serverpath(username, user_relpath)
    dirpath = os.path.dirname(filepath)
    if not os.path.isdir(dirpath):
        os.makedirs(dirpath)
    with open(filepath, 'wb') as fp:
        fp.write(content)
    mtime = os.path.getmtime(filepath)
    if update_userdata:
        server.userdata[username][server.SNAPSHOT][user_relpath] = [int(mtime),
                                                                    server.calculate_file_md5(open(filepath, 'rb'))]
    return mtime


def create_user_dir(username):
    """
    Create user directory (must not exist)
    :param username:
    :return:
    """
    os.makedirs(userpath2serverpath(username))


def build_tstuser_dir(username):
    """
    Create a directory with files and return its structure
    in a list.
    :param username: str
    :return: tuple
    """
    # md5("foo") = "acbd18db4cc2f85cedef654fccc4a4d8"
    # md5("bar") = "37b51d194a7513e45b56f6524f2d51f2"
    # md5("spam") = "e09f6a7593f8ae3994ea57e1117f67ec"
    file_contents = [
        ('spamfile', 'spam', 'e09f6a7593f8ae3994ea57e1117f67ec'),
        (os.path.join('subdir', 'foofile.txt'), 'foo', 'acbd18db4cc2f85cedef654fccc4a4d8'),
        (os.path.join('subdir', 'barfile.md'), 'bar', '37b51d194a7513e45b56f6524f2d51f2'),
    ]

    user_root = userpath2serverpath(username)
    # If directory already exists, destroy it
    if os.path.isdir(user_root):
        shutil.rmtree(user_root)
    os.mkdir(user_root)
    expected_timestamp = None
    expected_snapshot = {}
    for user_filepath, content, md5 in file_contents:
        expected_timestamp = int(_create_file(username, user_filepath, content))
        expected_snapshot[user_filepath] = [expected_timestamp, unicode(md5)]
    return expected_timestamp, expected_snapshot


def _manually_create_user(username, pw):
    enc_pass = server._encrypt_password(pw)
    single_user_data = {server.PASSWORD: enc_pass,
                        server.LAST_SERVER_TIMESTAMP: server.now_timestamp(),
                        server.SNAPSHOT: {}}  # set empty directory as snapshot
    server.userdata[username] = single_user_data
    create_user_dir(username)


def _manually_remove_user(username):  # TODO: make this from server module
    # WARNING: Removing the test-user manually from db if it exists!
    # (is it the right way to make sure that the test user don't exist?)
    if USR in server.userdata:
        server.userdata.pop(username)
    # Remove user directory if exists!
    user_dirpath = userpath2serverpath(USR)
    if os.path.exists(user_dirpath):
        shutil.rmtree(user_dirpath)
        logging.info('"%s" user directory removed' % user_dirpath)
    else:
        logging.info('"%s" user directory does not exist...' % user_dirpath)


def setup_test_dir():
    """
    Create (if needed) <TEST_DIR> directory starting from current directory and change current directory to the new one.
    """
    try:
        os.mkdir(TEST_DIR)
    except OSError:
        pass

    os.chdir(TEST_DIR)


def tear_down_test_dir():
    """
    Return to initial directory and remove the <TEST_DIR> one.
    """
    os.chdir(start_dir)
    shutil.rmtree(TEST_DIR)


class TestRequests(unittest.TestCase):
    def setUp(self):
        """
        Create an user and create the test file to test the download from server.
        """
        setup_test_dir()

        self.app = server.app.test_client()
        self.app.testing = True
        # To see the tracebacks in case of 500 server error!
        server.app.config.update(TESTING=True)

        _manually_remove_user(USR)
        _manually_create_user(USR, PW)

    def tearDown(self):
        _manually_remove_user(USR)
        tear_down_test_dir()

    def test_files_post_with_auth(self):
        """
        Test for authenticated upload.
        """
        user_relative_upload_filepath = 'testupload/testfile.txt'
        upload_test_url = SERVER_FILES_API + user_relative_upload_filepath
        uploaded_filepath = userpath2serverpath(USR, user_relative_upload_filepath)
        assert not os.path.exists(uploaded_filepath), '"{}" file is existing'.format(uploaded_filepath)

        test = self.app.post(upload_test_url,
                             headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                             data=dict(file=(io.BytesIO(b'this is a test'), 'test.pdf'),),
                             follow_redirects=True)
        self.assertEqual(test.status_code, server.HTTP_CREATED)
        self.assertTrue(os.path.isfile(uploaded_filepath))
        os.remove(uploaded_filepath)
        logging.info('"{}" removed'.format(uploaded_filepath))

    def test_files_post_with_not_allowed_path(self):
        """
        Test that creating a directory upper than the user root is not allowed.
        """
        user_filepath = '../../../test/myfile2.dat'  # path forbidden
        url = SERVER_FILES_API + user_filepath
        test = self.app.post(url,
                             headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                             data=dict(file=(io.BytesIO(b'this is a test'), 'test.pdf'),), follow_redirects=True)
        self.assertEqual(test.status_code, server.HTTP_FORBIDDEN)
        self.assertFalse(os.path.isfile(userpath2serverpath(USR, user_filepath)))

    def test_files_put_with_auth(self):
        path = 'test_put/file_to_change.txt'
        _create_file(USR, path, 'I will change')
        to_modify_filepath = userpath2serverpath(USR, path)

        url = SERVER_FILES_API + path
        test = self.app.put(url,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                            data=dict(file=(io.BytesIO(b'I have changed'), 'foo.foo')), follow_redirects=True)
        # TODO: check that content has changed
        self.assertEqual(test.status_code, server.HTTP_CREATED)  # 200 or 201 (OK or created)?

    def test_delete_file_path(self):
        """
        Test if a created file is deleted and assures it doesn't exists anymore with assertFalse
        """
        # create file to be deleted
        delete_test_url = SERVER_ACTIONS_API + 'delete'
        delete_test_file_path = 'testdelete/testdeletefile.txt'
        to_delete_filepath = userpath2serverpath(USR, delete_test_file_path)

        _create_file(USR, delete_test_file_path, 'this is the file to be deleted')

        test = self.app.post(delete_test_url,
                             headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                             data={'filepath': delete_test_file_path}, follow_redirects=True)

        self.assertEqual(test.status_code, server.HTTP_OK)
        self.assertFalse(os.path.isfile(to_delete_filepath))

    def test_copy_file_path(self):
        """
        Test if a created source file is copied in a new created destination and assures the source file
        still exists
        """
        copy_test_url = SERVER_ACTIONS_API + 'copy'
        src_copy_test_file_path = 'test_copy_src/testcopysrc.txt'
        dst_copy_test_file_path = 'test_copy_dst/testcopydst.txt'
        # Create source file to be copied and its destination.
        src_copy_filepath = userpath2serverpath(USR, src_copy_test_file_path)
        dst_copy_filepath = userpath2serverpath(USR, dst_copy_test_file_path)

        _create_file(USR, src_copy_test_file_path, 'this is the file to be copied')
        _create_file(USR, dst_copy_test_file_path, 'different other content')

        test = self.app.post(copy_test_url,
                             headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                             data={'src': src_copy_test_file_path, 'dst': dst_copy_test_file_path}, follow_redirects=True)

        self.assertEqual(test.status_code, server.HTTP_OK)
        self.assertTrue(os.path.isfile(src_copy_filepath))

    def test_move_file_path(self):
        """
        TTest if a created source file is moved in a new created destination and assures the source file
        doesn't exists after
        """
        move_test_url = SERVER_ACTIONS_API + 'move'
        src_move_test_file_path = 'test_move_src/testmovesrc.txt'
        dst_move_test_file_path = 'test_move_dst/testmovedst.txt'
        #create source file to be moved and its destination
        src_move_filepath = userpath2serverpath(USR, src_move_test_file_path)
        dst_move_filepath = userpath2serverpath(USR, dst_move_test_file_path)

        _create_file(USR, src_move_test_file_path, 'this is the file to be moved')

        test = self.app.post(move_test_url,
                             headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                             data={'src': src_move_test_file_path, 'dst': dst_move_test_file_path}, follow_redirects=True)

        self.assertEqual(test.status_code, server.HTTP_OK)
        self.assertFalse(os.path.isfile(src_move_filepath))


class TestGetRequests(unittest.TestCase):
    """
    Test get requests.
    """
    USER_RELATIVE_DOWNLOAD_FILEPATH = 'testdownload/testfile.txt'
    DOWNLOAD_TEST_URL = SERVER_FILES_API + USER_RELATIVE_DOWNLOAD_FILEPATH

    def setUp(self):
        """
        Create an user with a POST method and create the test file to test the download from server.
        """
        setup_test_dir()

        self.app = server.app.test_client()
        self.app.testing = True
        # To see the tracebacks in case of 500 server error!
        server.app.config.update(TESTING=True)

        _manually_remove_user(USR)
        _manually_create_user(USR, PW)

        # Create temporary file
        server_filepath = userpath2serverpath(USR, self.USER_RELATIVE_DOWNLOAD_FILEPATH)
        if not os.path.exists(os.path.dirname(server_filepath)):
            os.makedirs(os.path.dirname(server_filepath))
        with open(server_filepath, 'w') as fp:
            fp.write('some text')

    def tearDown(self):
        server_filepath = userpath2serverpath(USR, self.USER_RELATIVE_DOWNLOAD_FILEPATH)
        if os.path.exists(server_filepath):
            os.remove(server_filepath)
        _manually_remove_user(USR)
        tear_down_test_dir()

    def test_files_get_with_auth(self):
        """
        Test that server return an OK HTTP code if an authenticated user request
        to download an existing file.
        """
        test = self.app.get(self.DOWNLOAD_TEST_URL,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))})
        self.assertEqual(test.status_code, server.HTTP_OK)

    def test_files_get_existing_file_with_wrong_password(self):
        """
        Test that server return a HTTP_UNAUTHORIZED error if
        the user exists but the given password is wrong.
        """
        wrong_password = PW + 'a'
        test = self.app.get(self.DOWNLOAD_TEST_URL,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR,
                                                                                                 wrong_password))})
        self.assertEqual(test.status_code, server.HTTP_UNAUTHORIZED)

    def test_files_get_existing_file_with_empty_password(self):
        """
        Test that server return a HTTP_UNAUTHORIZED error if
        the user exists but the password is an empty string.
        """
        test = self.app.get(self.DOWNLOAD_TEST_URL,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, ''))})
        self.assertEqual(test.status_code, server.HTTP_UNAUTHORIZED)

    def test_files_get_existing_file_with_empty_username(self):
        """
        Test that server return a HTTP_UNAUTHORIZED error if
        the given user is an empty string and the password is not empty.
        """
        test = self.app.get(self.DOWNLOAD_TEST_URL,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format('', PW))})
        self.assertEqual(test.status_code, server.HTTP_UNAUTHORIZED)

    def test_files_get_existing_file_with_unexisting_user(self):
        """
        Test that server return a HTTP_UNAUTHORIZED error if
        the given user does not exist.
        """
        user = 'UnExIsTiNgUsEr'
        assert user not in server.userdata
        test = self.app.get(self.DOWNLOAD_TEST_URL,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(user, PW))})
        self.assertEqual(test.status_code, server.HTTP_UNAUTHORIZED)

    def test_files_get_without_auth(self):
        """
        Test unauthorized download of an existsing file.
        """
        # TODO: ensure that the file exists
        test = self.app.get(self.DOWNLOAD_TEST_URL)
        self.assertEqual(test.status_code, server.HTTP_UNAUTHORIZED)

    def test_files_get_with_not_existing_file(self):
        """
        Test that error 404 is correctly returned if an authenticated user try to download
        a file that does not exist.
        """
        test = self.app.get(SERVER_FILES_API + 'testdownload/unexisting.txt',
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))})
        self.assertEqual(test.status_code, server.HTTP_NOT_FOUND)

    def test_files_get_snapshot(self):
        """
        Test lato-server user files snapshot.
        """
        # The test user is created in setUp
        expected_timestamp, expected_snapshot = build_tstuser_dir(USR)
        target = {server.LAST_SERVER_TIMESTAMP: expected_timestamp,
                  server.SNAPSHOT: expected_snapshot}
        test = self.app.get(SERVER_FILES_API,
                            headers={'Authorization': 'Basic ' + base64.b64encode('{}:{}'.format(USR, PW))},
                            )
        self.assertEqual(test.status_code, server.HTTP_OK)
        obj = json.loads(test.data)
        self.assertEqual(obj, target)


class TestUsers(unittest.TestCase):
    def setUp(self):
        setup_test_dir()
        self.app = server.app.test_client()
        self.app.testing = True
        # To see the tracebacks in case of 500 server error!
        server.app.config.update(TESTING=True)

        _manually_remove_user(USR)

    def tearDown(self):
        tear_down_test_dir()

    def test_signup(self):
        """
        Test for registration of a new user.
        """
        test = self.app.post(urlparse.urljoin(SERVER_API, 'signup'),
                             data={'username': USR, 'password': PW})
        # test that userdata is actually updated
        single_user_data = server.userdata[USR]
        self.assertIn(USR, server.userdata)
        # test single user data structure (as currently defined)
        self.assertIsInstance(single_user_data, dict)
        self.assertIn(server.LAST_SERVER_TIMESTAMP, single_user_data)
        self.assertIn(server.SNAPSHOT, single_user_data)
        self.assertIsInstance(single_user_data[server.LAST_SERVER_TIMESTAMP], int)
        self.assertIsInstance(single_user_data[server.SNAPSHOT], dict)
        # test that the user directory is created
        user_dirpath = userpath2serverpath(USR)
        self.assertTrue(os.path.isdir(user_dirpath))
        # test server response
        self.assertEqual(test.status_code, server.HTTP_CREATED)

    def test_signup_if_user_already_exists(self):
        """
        Test for registration of an already existing username.
        """
        # First create the user
        _manually_create_user(USR, PW)
        # Then try to create a new user with the same username
        test = self.app.post(urlparse.urljoin(SERVER_API, 'signup'),
                             data={'username': USR, 'password': 'boh'})
        self.assertEqual(test.status_code, server.HTTP_CONFLICT)

    def test_signup_with_empty_username(self):
        """
        Test that a signup with empty user return a bad request error.
        """
        test = self.app.post(urlparse.urljoin(SERVER_API, 'signup'),
                             data={'username': '', 'password': 'pass'})
        self.assertEqual(test.status_code, server.HTTP_BAD_REQUEST)


if __name__ == '__main__':
    unittest.main()
