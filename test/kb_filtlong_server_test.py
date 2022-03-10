# -*- coding: utf-8 -*-
import os
import time
import unittest
from configparser import ConfigParser

import shutil
import requests

from kb_filtlong.kb_filtlongImpl import kb_filtlong
from kb_filtlong.kb_filtlongServer import MethodContext
from kb_filtlong.authclient import KBaseAuth as _KBaseAuth
from installed_clients.ReadsUtilsClient import ReadsUtils
from installed_clients.WorkspaceClient import Workspace
from installed_clients.DataFileUtilClient import DataFileUtil
from installed_clients.AbstractHandleClient import AbstractHandle as HandleService

class kb_filtlongTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.token = os.environ.get('KB_AUTH_TOKEN', None)
        cls.callbackURL = os.environ.get('SDK_CALLBACK_URL', None)
        print('CB URL: ' + cls.callbackURL)
        config_file = os.environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('kb_filtlong'):
            cls.cfg[nameval[0]] = nameval[1]
        cls.cfg["SDK_CALLBACK_URL"] = cls.callbackURL
        cls.cfg["KB_AUTH_TOKEN"] = cls.token
        cls.wsURL = cls.cfg['workspace-url']
        cls.shockURL = cls.cfg['shock-url']
        cls.hs = HandleService(url=cls.cfg['handle-service-url'],
                               token=cls.token)
        # Getting username from Auth profile for token
        authServiceUrl = cls.cfg['auth-service-url']
        auth_client = _KBaseAuth(authServiceUrl)
        user_id = auth_client.get_user(cls.token)
        # WARNING: don't call any logging methods on the context object,
        # it'll result in a NoneType error
        cls.ctx = MethodContext(None)
        cls.ctx.update({'token': cls.token,
                        'user_id': user_id,
                        'provenance': [
                            {'service': 'kb_filtlong',
                             'method': 'please_never_use_it_in_production',
                             'method_params': []
                             }],
                        'authenticated': 1})
        cls.wsURL = cls.cfg['workspace-url']
        cls.wsClient = Workspace(cls.wsURL)
        cls.serviceImpl = kb_filtlong(cls.cfg)
        cls.scratch = cls.cfg['scratch']
        suffix = int(time.time() * 1000)
        cls.wsName = "test_ContigFilter_" + str(suffix)
        cls.wsinfo = cls.wsClient.create_workspace({'workspace': cls.wsName})
        print('created workspace ' + cls.getWsName())

        cls.PROJECT_DIR = 'filtlong_outputs'
        if not os.path.exists(cls.scratch):
            os.makedirs(cls.scratch)
        cls.prjdir = os.path.join(cls.scratch, cls.PROJECT_DIR)
        if not os.path.exists(cls.prjdir):
            os.makedirs(cls.prjdir)

        cls.readUtilsImpl = ReadsUtils(cls.callbackURL, token=cls.token)
        cls.dfuClient = DataFileUtil(url=cls.callbackURL, token=cls.token)
        cls.staged = {}
        cls.nodes_to_delete = []
        cls.handles_to_delete = []
        cls.setupTestData()
        print('\n\n=============== Starting Filtlong tests ==================')

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'wsName'):
            cls.wsClient.delete_workspace({'workspace': cls.wsName})
            print('Test workspace was deleted')
        if hasattr(cls, 'nodes_to_delete'):
            for node in cls.nodes_to_delete:
                cls.delete_shock_node(node)
        if hasattr(cls, 'handles_to_delete'):
            if cls.handles_to_delete:
                cls.hs.delete_handles(cls.hs.hids_to_handles(cls.handles_to_delete))
                print('Deleted handles ' + str(cls.handles_to_delete))

    @classmethod
    def getWsName(cls):
        return cls.wsinfo[1]

    def getImpl(self):
        return self.serviceImpl

    @classmethod
    def delete_shock_node(cls, node_id):
        header = {'Authorization': 'Oauth {0}'.format(cls.token)}
        requests.delete(cls.shockURL + '/node/' + node_id, headers=header,
                        allow_redirects=True)
        print('Deleted shock node ' + node_id)

    @classmethod
    def upload_file_to_shock_and_get_handle(cls, test_file):
        '''
        Uploads the file in test_file to shock and returns the node and a
        handle to the node.
        '''
        # file can't be in /kb/module/test or dfu won't find it
        temp_file = os.path.join("/kb/module/work/tmp", os.path.basename(test_file))
        shutil.copy(os.path.join("/kb/module/test", test_file), temp_file)

        print('loading file to shock: ' + test_file)
        fts = cls.dfuClient.file_to_shock({'file_path': temp_file,
                                           'make_handle':True})

        cls.nodes_to_delete.append(fts['shock_id'])
        cls.handles_to_delete.append(fts['handle']['hid'])

        return fts['shock_id'], fts['handle']['hid'], fts['size']

    @classmethod
    def upload_reads(cls, wsobjname, object_body, fwd_reads,
                     rev_reads=None, single_end=False, sequencing_tech='Illumina',
                     single_genome='1'):

        ob = dict(object_body)  # copy
        ob['sequencing_tech'] = sequencing_tech
        ob['wsname'] = cls.getWsName()
        ob['name'] = wsobjname
        if single_end or rev_reads:
            ob['interleaved'] = 0
        else:
            ob['interleaved'] = 1
        print('\n===============staging data for object ' + wsobjname +
              '================')
        print('uploading forward reads file ' + fwd_reads['file'])
        fwd_id, fwd_handle_id, fwd_size = \
            cls.upload_file_to_shock_and_get_handle(fwd_reads['file'])

        ob['fwd_id'] = fwd_id
        rev_id = None
        rev_handle_id = None
        if rev_reads:
            print('uploading reverse reads file ' + rev_reads['file'])
            rev_id, rev_handle_id, rev_size = \
                cls.upload_file_to_shock_and_get_handle(rev_reads['file'])
            ob['rev_id'] = rev_id
        obj_ref = cls.readUtilsImpl.upload_reads(ob)
        objdata = cls.wsClient.get_object_info_new({
            'objects': [{'ref': obj_ref['obj_ref']}]
            })[0]
        cls.staged[wsobjname] = {'info': objdata,
                                 'ref': cls.make_ref(objdata),
                                 'fwd_node_id': fwd_id,
                                 'rev_node_id': rev_id,
                                 'fwd_handle_id': fwd_handle_id,
                                 'rev_handle_id': rev_handle_id
                                 }

    @classmethod
    def setupTestData(cls):
        print('Shock url ' + cls.shockURL)
        # print('WS url ' + cls.wsClient.url)
        # print('Handle service url ' + cls.hs.url)
        print('staging data')

        long_reads_high_depth = {'file': 'data/long_reads_high_depth.fastq.gz',
                     'name': 'long_reads_high_depth.fastq.gz',
                     'type': ''}
        cls.upload_reads('shigella_long_high', {'single_genome': 1}, long_reads_high_depth,
                         single_end=True, sequencing_tech="PacBio")
        print('Data staged.')

    @classmethod
    def make_ref(self, object_info):
        return str(object_info[6]) + '/' + str(object_info[0]) + \
            '/' + str(object_info[4])

    # NOTE: According to Python unittest naming rules test method names should start from 'test'. # noqa
    def run_filtlong(self,
                     output_reads_name,
                     long_reads_library = None,
                     min_read_length = 1000,
                     keep_percent = 90,
                     target_bases = None):
        params = {'workspace_name': self.getWsName(),
                  'input_reads_library': long_reads_library,
                  'output_reads_name': output_reads_name,
                  'min_read_length': min_read_length,
                  'keep_percent': keep_percent,
                  'target_bases': target_bases
                  }
        
        ret = self.serviceImpl.run_kb_filtlong(self.ctx, params)[0]
        self.assertReportOK(ret, output_reads_name)

    def assertReportOK(self, ret_obj, reads_name):
        """
        assertReportAssembly: given a report object, check the object existence
        """
        report = self.wsClient.get_objects2({
                        'objects': [{'ref': ret_obj['report_ref']}]})['data'][0]
        self.assertEqual('KBaseReport.Report', report['info'][2].split('-')[0])
        self.assertEqual(1, len(report['data']['objects_created']))
        self.assertEqual('Filtered reads',
                         report['data']['objects_created'][0]['description'])
        self.assertIn('Filtered ', report['data']['text_message'])
        print("**************Report Message*************\n")
        print(report['data']['text_message'])

        reads_ref = report['data']['objects_created'][0]['ref']
        reads = self.wsClient.get_objects([{'ref': reads_ref}])[0]

        self.assertEqual('KBaseGenomeAnnotations.Assembly', assembly['info'][2].split('-')[0])
        self.assertEqual(1, len(assembly['provenance']))
        self.assertEqual(assembly_name, assembly['data']['assembly_id'])

        temp_handle_info = self.hs.hids_to_handles([assembly['data']['fasta_handle_ref']])
        assembly_fasta_node = temp_handle_info[0]['id']
        self.nodes_to_delete.append(assembly_fasta_node)

    # Uncomment to skip this test
    # @unittest.skip("skipped test test_shigella_long_kbfile")
    def test_shigella_long_kbfile(self):
        self.run_filtlong( 'shigella_long_out',
                           long_reads_library='shigella_long_high')
        
