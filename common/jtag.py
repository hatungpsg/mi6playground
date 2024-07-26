from fwval_lib.common import *
from fwval_lib.common.platform_system_console import start_systemconsole as startscon
from fwval_lib.security.puf import PufAdd
import binascii
import execution_lib
import logging
import os
import pycv as fwval
import random
import re
import subprocess
# To dump the sector memory and compare with golden bitstream image
if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
    from fwval_lib.common.emu_utils import *
    # from cram_collector_compare_all import cram_collector_compare_all

revision = "$Revision: #41 $"
__version__ = 0
try: __version__ = int([''.join([str(s) for s in [c for c in revision] if s.isdigit()])][0])
except: pass
cv_logger.info("%s current rev: #%s" % (__name__, __version__))
cv_logger.info("%s source: %s" % (__name__, __file__))

###########################################################################################
#   Empty Class
###########################################################################################
#This is our empty test environment. Used for initializing if needed (usually not needed)
class EmptyTest(object):
    def __init__(self):
        self.dut = None

###########################################################################################
#    JTAG
###########################################################################################
#This is a Base Class. It is the class for jtag dut
#This class will have the common variables & functions for all duts
#We will inherit it for other specific test uses (eg. to add AVST onto it)
class JtagTest(EmptyTest):
    '''
    Input   : - configuration, msel, for fwval.platform_init(), default "jtag" and 8 respectively
              config_done_sdmio, init_done_sdmio, have default values "sdmio_0" and "sdmio_16"
              you can disable these pins by giving None
              - jtagid -- required when using configuration='jtag_dut'
              - daughter_card -- Set dc = 1 if the test is using a physical QSPI flash. If no value is
                                 given, Sdmio Class will auto assign a value based on the platform
              - rev -- used for specify revision (string contain a,b,c, etc). if not specified, will be
                       taken from os.environ['DUT_REV']
              - device_idx -- sets the fwval connector index, by default it will always select index 1
                              NOTE :: If no device_idx defined, for ND7M devices,
                                      default will select DUT1/HELPER1 which is index 2
    Mod     : self -- initialize the test object
    '''
    def __init__(self, configuration="jtag", msel=8, rev="", daughter_card=None, config_done_sdmio="", init_done_sdmio="sdmio_0", device_idx=1, jtagid=None):
        #kill all syscon before starting test
        kill_all_syscon()
        #HSD15014949654: Call socedstest script to power cycle the board before test start
        soceds_power_cycle()
        #private variables, used by the object itself
        if rev == "":
            self._REV = os.environ['DUT_REV']
        else:
            self._REV = rev
        self._BASE_DIE = os.environ['DUT_BASE_DIE']
        self._BFM_CONFIG = configuration
        self._MSEL   = int(msel)
        self._DEVICE_IDX = int(device_idx)
        cv_logger.info("My device_idx in JTAGTEST : %d" %self._DEVICE_IDX)
        self._sdmio = Sdmio(configuration=configuration,msel=msel,daughter_card=daughter_card,dut_sdm_conf_done=config_done_sdmio)
        self._CONFIG_DONE = self._sdmio.get_conf_done_sdmio()
        cv_logger.info("CONFIG_DONE : %s" % self._CONFIG_DONE)
        self._INIT_DONE = init_done_sdmio
        self._verify_counter = 0        #counter for pin, status, and design verification
        self._config_counter = 0        #counter for configurations (sending bitstream)
        self._fuse_write_disabled = False     #signify if we disabled fuse writing. don't touch this
        self._UDS_TEST_MODE = None
        self.RH_SLOT_COUNT = ROOT_HASH_SLOT_MAXCOUNT["default"]

        #get dut family
        try:
            self.platform_test = PlatformTest()
            self.platform_test.platform_identification()
            self.DUT_FILTER = self.platform_test.platform_properties
            self.DUT_FAMILY = self.DUT_FILTER.dut_family
        except:
            print_err("\nTEST_RESULT :: FAILED DUT PLATFORM IDENTIFICATION")
            #log the traceback into stderr
            logging.exception('')

            #check if any sys-console left and kill them
            self._lib_delay()
            kill_all_syscon()
            exit(-1)

        #expected values, these are public (meaning it's ok to change them in main code)
        #expected pin
        self.exp_pin = {
                           'NSTATUS'         : 0,
                           'INIT_DONE'       : 0,
                           'CONFIG_DONE'     : 0,
                           'AVST_READY'      : 0
        }
        #expected status
        self.exp_status = {
                               'STATE'            : 0,
                               'VERSION'          : self.get_expected_version(),
                               'NSTATUS'          : 0,
                               'NCONFIG'          : 0,
                               'MSEL_LATCHED'     : 0xFEABD,
                               'CONFIG_DONE'      : 0,
                               'INIT_DONE'        : 0,
                               'CVP_DONE'         : 0,
                               'SEU_ERROR'        : 0,
                               'ERROR_LOCATION'   : 0,
                               'ERROR_DETAILS'    : 0,
                               'POR_WAIT'         : 0,
                               'TRAMP_DSBLE'      : 0,
                               'BETALOADER'       : 0,
                               'PROVISION_CMF'    : 0,
        }

        # expected provision status
        # FM6, DMD support up to 3 slots
        # FM7 and above support up to 5 slots
        self.exp_prov_status = {
                                'SKIP_PROV_CMD'                             : 0,
                                'PROV_STATUS_CODE'                          : 0,
                                'INTEL_CANC_STATUS'                         : 0,
                                'COSIGN_STATUS'                             : 0,
                                'OWNER_RH0_CANC_STATUS'                     : 0,
                                'OWNER_RH1_CANC_STATUS'                     : 0,
                                'OWNER_RH2_CANC_STATUS'                     : 0,
                                'OWNER_RH3_CANC_STATUS'                     : 0,
                                'OWNER_RH4_CANC_STATUS'                     : 0,
                                'HASH_COUNT'                                : 0,
                                'HASH_TYPE'                                 : 2, # 2:secp384r1
                                'HASH_SLOT_VALID_STATUS'                    : 0,                                
                                'OWNER_RH0'                                 : [0],
                                'OWNER0_EXPKEY_CANC_STATUS'                 : 0,
                                'OWNER_RH1'                                 : [0],
                                'OWNER1_EXPKEY_CANC_STATUS'                 : 0,
                                'OWNER_RH2'                                 : [0],
                                'OWNER2_EXPKEY_CANC_STATUS'                 : 0,
                                'OWNER_RH3'                                 : [0],
                                'OWNER3_EXPKEY_CANC_STATUS'                 : 0,
                                'OWNER_RH4'                                 : [0],
                                'OWNER4_EXPKEY_CANC_STATUS'                 : 0,
                                'BIG_COUNTER_BASE'                          : 0,
                                'BIG_COUNTER'                               : 0,
                                'SVN3'                                      : 0,
                                'SVN2'                                      : 0,
                                'SVN1'                                      : 0,
                                'SVN0'                                      : 0,
                                'eFUSE_IFP_KEY_SLOT_STATUS5'                : 0,
                                'eFUSE_IFP_KEY_SLOT_STATUS4'                : 0,
                                'eFUSE_IFP_KEY_SLOT_STATUS3'                : 1,
                                'eFUSE_IFP_KEY_SLOT_STATUS2'                : 1,
                                'eFUSE_IFP_KEY_SLOT_STATUS1'                : 1,
                                'eFUSE_IFP_KEY_SLOT_STATUS0'                : 1,
                                'KEY_SLOT_STATUS_B31_24'                    : 0,								
                                'FLASH_IFP_KEY_SLOT_STATUS5'                : 1,
                                'FLASH_IFP_KEY_SLOT_STATUS4'                : 1,
                                'FLASH_IFP_KEY_SLOT_STATUS3'                : 1,
                                'FLASH_IFP_KEY_SLOT_STATUS2'                : 1,
                                'FLASH_IFP_KEY_SLOT_STATUS1'                : 1,
                                'FLASH_IFP_KEY_SLOT_STATUS0'                : 1,																
                                'KEY_SLOT_B31_24'                           : 0,
                                'KEY_SLOT_B23_20'                           : 0,
                                'KEY_SLOT_B19_16'                           : 0,
                                'KEY_SLOT_B15_12'                           : 0,
                                'KEY_SLOT_B11_08_OCSKEY_1'                  : 1,    # TODO: Update OCSKEY. See HSD:15012276031
                                'KEY_SLOT_B07_04_OCSKEY_0'                  : 1,    # TODO: Update OCSKEY. See HSD:15012276031
                                'KEY_SLOT_B03_00_UAESKEY_0'                 : 0,
                                'FPM_CTR_VALUE'                             : 0,								
                                'OWNERSHIP_TRANSFER_MODE_STATUS'            : 0,
                                'NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES': 0,								
        }
        self.exp_prov_status_backup = self.exp_prov_status.copy()

        self._scoreboard_state = {
                                'secondary_ownership_pk'    : 0,
                                'sec_owner_auth_flag'       : 0, # test owner to manipulate this value
                                'intel_canc_exp_update_done': 0,
                                'pr_rh_prov_done'           : 0,
                                'ext_auth_rh_prov_done'     : 0,
        }
        self._scoreboard_state_backup = self._scoreboard_state.copy()

        #expected rsu status
        self.exp_rsu_status = {
                               'CURRENT_IMAGE_0'    : 0,
                               'CURRENT_IMAGE_1'    : 0,
                               'LAST_FAIL_IMAGE_0'  : 0,
                               'LAST_FAIL_IMAGE_1'  : 0,
                               'STATE'              : 0,
                               'VERSION'          : self.get_expected_version(),
                               'ERROR_LOCATION'   : 0,
                               'ERROR_DETAILS'    : 0
        }

        #issp properties
        self.issp_prop = {
                               'instance_index'   : None,
                               'source_width'     : None,
                               'probe_width'      : None,
        }

        #get dut
        try:
            # when running on mudv, qspi configuration with daughter card enabled, jtag bfm is force to be used to avoid conf_done pin corruption

            if configuration == 'jtag_dut':
                assert_err(jtagid != None, "ERROR :: jtagid not defined for jtag_dut configuration")
                self.dut = fwval.none_ftfw_platform_init(jtagid=jtagid, device_index=0)
            elif self._sdmio.platform == 'mudv' and self._BFM_CONFIG == 'qspi' and daughter_card == True:
                self.dut = fwval.platform_init(configuration='jtag', msel_value=self._MSEL)
            else:
                self.dut = fwval.platform_init(configuration=self._BFM_CONFIG, msel=self._MSEL)
            
            self.dut_cable = self.dut.dut_cable
            #update msel expectation
            self.exp_status['MSEL_LATCHED'] = int(msel)

            # when configuration is jtag_dut, it calls the none_ftfw_platform_init and most of the connectors are not available therefore have to be skipped
            if configuration != 'jtag_dut':
                #get general connectors
                self.power = self.dut.get_connector("power")
                assert_err(self.power != None, "ERROR :: Cannot open power Connector")
                self.nconfig = self.dut.get_connector("nconfig",self._DEVICE_IDX)
                assert_err(self.nconfig != None, "ERROR :: Cannot open nconfig Connector")
                self.nstatus = self.dut.get_connector("nstatus",self._DEVICE_IDX)
                assert_err(self.nstatus != None, "ERROR :: Cannot open nstatus Connector")
                # some test uses jtagtest class with msel=qspi
                # the qspi connector will be overwritten by QspiTest/RsuTest class later
                self.qspi = self.dut.get_connector("qspi")
                assert_err(self.qspi != None, "ERROR :: Cannot open the QSPI Connector")
                self._lib_delay()
                if self._sdmio.platform == 'mudv' :
                    self.bmc = self.dut.get_connector("bmc")
                    cv_logger.info("get_connector bmc")
                    assert_err(self.bmc != None, "ERROR :: Cannot open bmc Connector")
                    if self._MSEL == 9 and daughter_card == 1 :
                        self.bmc.set_sdm_dc_en(True)
                if self._CONFIG_DONE != None:
                    self.config_done = self.dut.get_connector(self._CONFIG_DONE,self._DEVICE_IDX)
                    self._lib_delay()
                    assert_err(self.config_done != None, "ERROR :: Cannot open config_done (%s) Connector" %self._CONFIG_DONE)
                else:
                    self.config_done = None
                    cv_logger.warning("User disabled the CONFIG_DONE gpio connector")
                if self._INIT_DONE != None:
                    self.init_done = self.dut.get_connector(self._INIT_DONE,self._DEVICE_IDX)
                    assert_err(self.init_done != None, "ERROR :: Cannot open init_done (%s) Connector" %self._INIT_DONE)
                else:
                    self.init_done = None
                    cv_logger.warning("User disabled the INIT_DONE gpio connector")

            self.jtag = self.dut.get_connector("jtag",self._DEVICE_IDX)
            self._lib_delay()
            assert_err(self.jtag != None, "ERROR :: Cannot open the JTAG Connector")
            if ((msel == 9) or (msel == 11)):
                try:
                    self.erase_qspi_die()
                except Exception as e:
                    # failed to initialize qspi should not block the execution
                    cv_logger.warning(str(e))
                    cv_logger.warning("QSPI Flash erase failed. Proceed anyway..")

        except:
            print_err("\nTEST_RESULT :: FAILED JTAG PLATFORM INITIALIZATION")
            #log the traceback into stderr
            logging.exception('')

            #check if any sys-console left and kill them
            self._lib_delay()
            kill_all_syscon()
            exit(-1)
        self._lib_delay()

        #other connectors (eg avst) should be gotten in the inherited classes

        # Added TSBL support
        self.ssbl_to_tsbl()

        # auto determine number of root hash slot supported
        for _name in ROOT_HASH_SLOT_MAXCOUNT :
            if _name in self._BASE_DIE :
                self.RH_SLOT_COUNT = ROOT_HASH_SLOT_MAXCOUNT[_name]
        cv_logger.info("%s support up to %s root hash slot" % (self._BASE_DIE, self.RH_SLOT_COUNT))

    '''
    Optional: chip select -- 0 Write the value of the flash device you want to select
              start_address -- 0 the start address of the flash
              size -- 512, 1024. die size in Mbit
              power_cycle -- True, power cycle after flash erasure
              timeout -- 60s to send dut helper image
    Modify  : Erase flash and power_cycle mudv
              1. power on dut
              2. capture nconfig and set nconfig to 1
              3. send config_jtag and program dut with helper via jtag 
              4. qspi open
              5. qspi chip select
              6. qspi erase flash from address of (start_address + size)
              7. qspi close
              8. power cycle and restore nconfig value
    Output  : None
    '''  
    def erase_qspi_die(self, chip_select=0, start_address=0, size=None, power_cycle=True, skip_helper=False, timeout=60):
        
        old_nconfig = self.nconfig.get_output()

        if self._sdmio.platform in ['oscar', 'emulator', 'simics', 'oscarbb']:
            pass
        elif self._sdmio.platform == 'mudv':
            # if user does not define erase die size, read from board resource
            if (size == None):
                size = os.environ.get('DUT_QSPI_DEVICE_DENSITY')
                if (size != None) :
                    size = int(size)
                    cv_logger.info("Read board resource, QSPI flash size %d Mb..." %size)
                
                if(os.environ['DUT_TYPE'] != 'Coville Ridge'):
                    #based on physical QSPI flash on board
                    #typically MT25QU02G = 2048 Mbit, assuming SOF file will occupy ~16Mbit
                    if (size == None):
                        size = 512
                        cv_logger.info("Cannot get DUT_QSPI_DEVICE_DENSITY from board resource, assign QSPI erase size %d Mb..." %size)
                else:
                    assert size!=None, "ERROR :: Failed to get DUT_QSPI_DEVICE_DENSITY from board resource"

            if (not skip_helper):    
                # prepare helper image
                cv_logger.info("Prepare DUT helper image...")
                helper = execution_lib.getsof(input_sof_flag=0,input_file='or_gate_design.x4.77MHZ_IOSC.sof',mode="sof2rbf", conf="qspi")
                pem_file = "iid_puf/auth_keys/agilex_ec_priv_384_test.pem"
                qky_file = "iid_puf/auth_keys/agilex_ec_384_test.qky"
                signed_helper = "signed_helper_file.rbf"

                if (os.path.exists(pem_file) and os.path.exists(qky_file)):
                    cv_logger.info("Use signed helper image instead of unsigned helper image")
                    run_command("quartus_sign --family=agilex --operation=sign --pem=%s --qky=%s %s %s" %(pem_file,qky_file,helper,signed_helper))
                    helper = signed_helper
                
                cv_logger.info("Avoid boot from old flash at the beginning of config")
                self.power_cycle(nconfig=0)

                # wait for sdm to finish processing previous bitstream from flash if any. assume 20s
                cv_logger.info("Wait 20s before issuing CONFIG_JTAG...")
                delay(20000)
            
                self.config_jtag()
                self.send_jtag(file_path=helper, success=1, timeout=timeout)
			
            cv_logger.info("Erasing flash die from address 0x%x with size %d Mbit..." % (start_address, size))
            self.dut.test_time()
            status = True
            status = self.qspi.qspi_open()
            assert status==1, "ERROR :: Failed to open QSPI interface"
            
            # Set Chip Select to decide which daughter card
            status = self.qspi.qspi_set_cs(chip_select)
            assert status==1, "ERROR :: Failed to chip select qspi"
            
            # sector erase code for future reference. one sector 64kb
            # offset = 0
            # while status and offset < size :
            #     status = self.qspi.qspi_sector_erase(start_address + offset)
            #     offset +=  64<<10
                
            cv_logger.info("QSPI_ERASE")
            # TODO: timeout, instead of explicitly put 1200s, calculate based on erase size
            # Data on time taken needed, erase time limit is not clearly defined
            self.qspi.qspi_die_erase(start_address, size, timeout=1200)
                
            # Close exclusive access to QSPI interface
            status = self.qspi.qspi_close()
            assert status, "ERROR :: Fail to close QSPI Interface access"
            cv_logger.info("Time to erase flash die: %s" % self.dut.elapsed_time())

            if power_cycle:
                self.power_cycle(old_nconfig)
                
    '''
    Added support for TSBL - ND Rearch 21.1 and beyond now uses TSBL, ND 20.4.1 below and FM still uses SSBL (HSD :1508667742)
    '''
    def ssbl_to_tsbl(self,old_resource=False):

        if (old_resource):
            quartus_version = select_older_quartus(resource="release")
        else:
            quartus_version = os.environ['QUARTUS_VERSION']

        if (self.DUT_FAMILY == "stratix10" and quartus_version >= '21.1'):
            BOOTROM_DESCRIPTOR['ssbl_size'] = BOOTROM_DESCRIPTOR['tsbl_size']
            BOOTROM_DESCRIPTOR['ssbl_load_add'] = BOOTROM_DESCRIPTOR['tsbl_load_add']
            BOOTROM_DESCRIPTOR['ssbl_offset'] = BOOTROM_DESCRIPTOR['tsbl_offset']
            BOOTROM_DESCRIPTOR['hash_ssbl'] = BOOTROM_DESCRIPTOR['hash_tsbl']
            self.SSBL_TSBL = "TSBL"
            cv_logger.debug("Detected family: {} and ACDS Version: {}. Using {} values".format(self.DUT_FAMILY,quartus_version,self.SSBL_TSBL))
        else:
            BOOTROM_DESCRIPTOR['ssbl_size'] = [0x100,0x04]
            BOOTROM_DESCRIPTOR['ssbl_load_add'] = [0x104,0x04]
            BOOTROM_DESCRIPTOR['ssbl_offset'] = [0x108,0x04]
            BOOTROM_DESCRIPTOR['hash_ssbl'] = [0x140,0x64]
            self.SSBL_TSBL = "SSBL"
            cv_logger.debug("Detected family: {} and ACDS Version: {}. Using {} values".format(self.DUT_FAMILY,quartus_version,self.SSBL_TSBL))

    '''
    For emulator delay is multiplied emu_delay_multiplier.
    Input   : delay (millisecond)
    '''
    def _lib_delay(self, delays=1000) :

        emu_delay_multiplier = 120
        if (os.environ.get("FWVAL_PLATFORM") == 'emulator') :
            delay(delays * emu_delay_multiplier, self.dut)
        else :
            delay(delays, self.dut)

    '''
    Input   : dut_closed: set to 1 dut already closed
    Mod     : self -- main error handling to
                1. close dut if not yet
                2. collect trace
                3. kill remaining system console
    '''
    def main_error_handler(self, dut_closed=None):
        #if dut no closed, make sure to close it
        if(dut_closed):
            #get error
            local_reponse = self.dut.get_last_error()
            cv_logger.info("Last DUT ERROR :: %s" %local_reponse)
            #close dut
            cv_logger.info("Closing DUT...")
            try:
                self.dut.close()
            except:
                cv_logger.warning("DUT already closed! Check code if unexpected.")

        # collect trace when test failed
        if(dut_closed == None or dut_closed == False):
            self.collect_pgm_trace()

        # collect trace and gtrace
        self.dump_trace()
        self.get_gtrace_dump()

        #check if any sys-console left and kill them
        self._lib_delay()
        kill_all_syscon()

    '''
    Input   : nconfig: the nconfig value that the board will turn on with
    Optional: nconfig will be set to 1 by default
    Req     : nconfig must be 1 or 0
    Mod     : self -- power cycle the board (off, set nconfig, on)
    '''
    def power_cycle(self, nconfig=1):
        #power off
        cv_logger.info("Power off")
        self.power.set_power(False)
        #toggle the nconfig pin
        cv_logger.info("Set nconfig = %d" %nconfig)
        self.nconfig.set_input(nconfig)

        if (self._fuse_write_disabled):
            cv_logger.info("Reset fuse_write_disabled")
            self._fuse_write_disabled = False
            
        # reset internal prov_status scoreboard
        self.exp_prov_status = self.exp_prov_status_backup.copy()
        self._scoreboard_state = self._scoreboard_state_backup.copy()

        self._lib_delay()
        #power on
        cv_logger.info("Power on")
        self.power.set_power(True)
        self._lib_delay()

    '''
    Requires : board resources
    Output   : return true if device if OPN Number ended with "AS"
    '''
    def is_as_device(self,):
        try:
            device_sfe = os.environ['DUT_SFE']

            if (device_sfe == "1"):
                return True
            else:
                return False

        except:
            cv_logger.warning("Environment variable DUT_SFE not found, default NON_SFE is used")
            return False

    '''
    Requires  : acds resources
    Output    : returns firmware cancelled key, recorded by database at the top of the library, 0 mean no key is cancelled
    '''

    def get_cancelled_key_based_on_acds_version(self,):

        if (re.search('[Nn][Dd]', self._BASE_DIE) != None):
            KEY_CANCELLATION = KEY_CANCELLATION_DATABASE[0]
        else:
            KEY_CANCELLATION = KEY_CANCELLATION_DATABASE[1]

        index_number = 0
        current_acds_version      = os.environ['QUARTUS_VERSION']     #get acds version EG: 19.0
        current_acds_version_path = os.environ['QUARTUS_ROOTDIR']     #get acds path EG: /tools/acds/19.0/20/linux64/quartus
        current_acds_build        = os.environ['ACDS_BUILD_NUMBER']   #get acds build number

        #Function to compare acds version, if left side latest than right side, return >  0 else return <  0, if same version then = 0
        def compare_version(acds_version1, acds_version2):
            def normalize(v):
                return [int(x) for x in re.sub(r'(\.0+)*$','', v).split(".")]
            return cmp(normalize(acds_version1), normalize(acds_version2))

        ##############################################
        ## Compare first item and last item before loop ##
        ##############################################
        #Compare first item, if current version smaller than the first data in data base, then no key cancelled
        acds_version_build, cancelled_key = KEY_CANCELLATION[0]
        acds_version = acds_version_build.split("/")[0]
        acds_build   = acds_version_build.split("/")[1]

        if ((compare_version(current_acds_version, acds_version) < 0) or ((compare_version(current_acds_version, acds_version) == 0) and (current_acds_build < acds_build))):
            cv_logger.info("TEST :: Cancelled Key is 0")
            return 0

        #Compare last item, if current version later than the last data in database, key cancelled = last data in database
        acds_version_build, cancelled_key = KEY_CANCELLATION[-1]
        acds_version = acds_version_build.split("/")[0]
        acds_build   = acds_version_build.split("/")[1]

        if ((compare_version(current_acds_version, acds_version) > 0) or ((compare_version(current_acds_version, acds_version) == 0) and (current_acds_build > acds_build))):
            cv_logger.info("TEST :: Cancelled Key is %s" %(cancelled_key))
            return cancelled_key

        ##############################
        ## Compare other posibility ##
        ##############################
        prevItem  = -1;
        ItemCount = 0;
        for acds_version_build, cancelled_key in KEY_CANCELLATION:
            acds_version = acds_version_build.split("/")[0]
            acds_build   = acds_version_build.split("/")[1]

            #If both acds version number are equal
            if (compare_version(current_acds_version, acds_version) == 0):
                #if both acds version number are the same then compare the build number
                if (current_acds_build == acds_build):
                    #if both build number are the same then exit loop, and take the cancelled key
                    break

                #If current acds_build > database_build number
                elif (current_acds_build > acds_build):
                    #record it down first
                    prevItem = ItemCount;

                #If current acds_build < database_build number
                elif (current_acds_build < acds_build):
                    if (prevItem != -1):
                        cancelled_key = KEY_CANCELLATION[prevItem][1]
                        break

            elif (compare_version(current_acds_version, acds_version) > 0):
                #record it down first
                prevItem = ItemCount;
            elif (compare_version(current_acds_version, acds_version) < 0):
                #If Current acds_version
                if (prevItem != -1):
                    cancelled_key = KEY_CANCELLATION[prevItem][1]
                    break
            ItemCount = ItemCount + 1  #To count the number of element

        cv_logger.info("TEST :: Cancelled Key is %s" %(cancelled_key))
        return cancelled_key


    '''
    Input     : bitstream --  bytearray of the bitstream
    Output    : returns fw_key for currently loaded fw, the key id used for the firmware signing
    '''
    def get_fw_key_by_bitstream(self, file):

        cv_logger.info("Bitstream processing to get firmware key ID.")

        #Convert bitstrean to byte array
        bitstream       = self.read_bitstream(file)

        #0x1000 is the 4k block
        index_signature                    = 0x1000

        #0x60 is the size of signature descriptor for nadder after this will be root entry
        index_root_entry                   = index_signature + 0x60
        cv_logger.info("Root Entry located at 0x%08x" %index_root_entry)
        #To get the length of the Root entry, adding this length will move to public key entry
        index_root_entry_start             = index_root_entry + ROOT_ENTRY[self.DUT_FAMILY]['length'][0]
        cv_logger.info("Root entry length start recorded at 0x%08x" %index_root_entry_start)

        #To get the number of byte of the length information
        index_root_entry_length_end        = index_root_entry_start + ROOT_ENTRY[self.DUT_FAMILY]['length'][1]
        cv_logger.info("Root entry length end recorded at 0x%08x" %index_root_entry_length_end)

        #To get the public key entry by adding the index of root entry and the root entry size(read from bit stream)
        index_public_key_entry_start       = index_root_entry + self.read_add(bitstream, index_root_entry_start, index_root_entry_length_end)
        cv_logger.info("Public Key entry located at 0x%08x" %index_public_key_entry_start)

        #To get the key cancellation entry by adding the
        index_key_cancellation_entry_start = index_public_key_entry_start + PUBLIC_ENTRY[self.DUT_FAMILY]['cancellation'][0]
        cv_logger.info("Key cancellation entry start recorded at 0x%08x" %index_key_cancellation_entry_start)

        #To get the key cancellation end
        index_key_cancellation_entry_end   = index_key_cancellation_entry_start + PUBLIC_ENTRY[self.DUT_FAMILY]['cancellation'][1]
        cv_logger.info("Key cancellation entry end recorded at 0x%08x" %index_key_cancellation_entry_end)

        #To get the key cancellation location
        key_cancellation                   =  self.read_add(bitstream, index_key_cancellation_entry_start, index_key_cancellation_entry_end )
        cv_logger.info("Running firmware Key ID 0x%x" %key_cancellation)

        return key_cancellation

    '''
    Requires  : NONE
    Output    : Returns expected cancelled value in the PSG Cancellation Fuse based on the currently loaded fw
    Modifies  : NONE
    '''
    def get_cancelled_psg_key(self):

        svn = get_cmf_security_version()
        dut_property = dut_properties()
        if dut_property.dut_family == "stratix10":
            if svn == 0: #key 1 firmware
                key_cancellation = 0
            elif svn == 1: #key 0 firmware
                key_cancellation = 2
            else:
                key_cancellation = pow(2,svn) - 1
        else:
            key_cancellation = pow(2,svn) -1  #indicate the expected bit value in Bank 2 Row 27 b31:b0

        cv_logger.info("Expected PSG CANCELLATION FUSE VALUES based on CMF SECURITY VERSION in bitstream is %d" %key_cancellation)

        return (key_cancellation)

    '''
    Requires  : fw must be loaded
    Output    : returns fw_key for currently loaded fw, the key id used for the firmware signing
    Modifies  : sends INTERNAL_DEBUG_READ command to fw
    '''

    def get_fw_key(self,):

        #Copy sof file to current directory
        cv_logger.info("Getting FW Key from pregen sof, copying sof to current folder")
        cv_logger.info("Converting sof to rbf")
        #ONLY for Nadder
        input_bitstream_file = "or_gate_design.x4.77MHZ_IOSC.sof";

        bitstream_file = execution_lib.getsof(input_file=input_bitstream_file,mode="sof2rbf")

        #Read fw key from the RBF
        cv_logger.info("Reading rbf file and get the cancelled key")
        FW_KEY = self.get_fw_key_by_bitstream(str(bitstream_file))

        # cv_logger.info("Getting fw key ID using INTERNAL_DEBUG_READ command...")

        return FW_KEY

    '''
    Check if the firmware key given is newer than the key we are checking against
    Input  -- both are integer like 1 or 0
    Output -- True or False
    Note: for ND device, the oldest key is 1, then 0, 2, ... 30
          for other devices, oldest key is 0, then 1, 2, ... 30
    '''
    def is_fw_eq_or_newer(self, fw_key, check_key):
        if (re.search('[Nn][Dd]', self._BASE_DIE) != None):
            if (fw_key == 0 and check_key == 1) or (fw_key == 1 and check_key == 0): #for ND device, the oldest key is 1
                return not (fw_key >= check_key)

        return (fw_key >= check_key)

    '''
    Mod     : self -- sends EFUSE_WRITE_DISABLE via jtag
                      sets self._fuse_write_disabled to be True
              Input -- True Shall skip the programming of the efuse_write_disable to handle HSD#1507406874
              skip_program -- True Shall skip the programming of the efuse_write_disable to handle HSD#1507406874
              test_mode -- 0 for using real UDS value, 1-3 for using different set of fake UDS value
    '''
    def efuse_write_disable(self,skip_program=None, test_mode=None):
        # This returns the expected value on psg key cancellation fuse
        # if skip_program == None:
        #     # based on the firmware signed key
        #     expected_psg_key_cancellation = self.get_cancelled_psg_key()

        #     # For firmware signed with keys other than limited key
        #     if expected_psg_key_cancellation:
        #         skip_program = True

        #     # For firmware signed with limited key
        #     else:
        #         skip_program = False

        #     cv_logger.info("Setting skip_program to %s" %skip_program)

        sdm_version = os.getenv('DUT_SDM_VERSION')
        dut_sfe = os.getenv('DUT_SFE')

        # use user input test mode, else check if it is sdm 1.5 non-sfe which require test mode
        if test_mode:
            self._UDS_TEST_MODE = test_mode
        elif (self._UDS_TEST_MODE is None and sdm_version == "1.5" and dut_sfe == "0"):
            self._UDS_TEST_MODE = random.randint(1, 3)
            cv_logger.warning("There is no UDS value on non-sfe, proceed with using UDS test mode value %d" % self._UDS_TEST_MODE)
        
        # Get the security version of the firmware if skip_program is None
        if(skip_program is None):
            security_version = get_cmf_security_version()
            if(security_version == 0):
                cv_logger.info("Detected limited signed firmware with security version %s, set skip_program to False" % security_version)
                skip_program = False
            else:
                cv_logger.info("Detected signed firmware with security version %s, set skip_program to True" % security_version)
                skip_program = True

        if(self._UDS_TEST_MODE is not None):
            cv_logger.info("Value of test mode used: %d " % self._UDS_TEST_MODE)
            if(self._UDS_TEST_MODE>3):
                assert_err(0, "ERROR :: Test mode must be in the range of 0-3")
            # AR YanSee : Add check to not allow test mode if the firmware is manufacturing key signed (only impact FM6). Refer HSD 1509798406
            if(self._UDS_TEST_MODE!=0 and self.DUT_FAMILY == "stratix10"):
                assert_err(0, "ERROR :: Nadder doesn't support attestation test mode")

        # send the command
        if(not skip_program):
            cv_logger.info("efuse_write_disable ===============================>")
            if(self._UDS_TEST_MODE is not None):
                resp = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_WRITE_DISABLE'],self._UDS_TEST_MODE)
            else:
                resp = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_WRITE_DISABLE'])

            # resp = self.jtag.packet_send_cmd(32, SDM_CMD['EFUSE_WRITE_DISABLE'])
            cv_logger.info("Response value : %s" %resp)
            assert_err(resp[0] == 0, "ERROR :: EFUSE_WRITE_DISABLE Failed!")
            # set the flag to true
            self._fuse_write_disabled = True
            cv_logger.info("Efuse write disabled...")
        else:
            self._fuse_write_disabled = False
            cv_logger.debug("The eFUSE WRITE DISABLED IS ASKED TO HANDLE SCENARIO captured in HSD#1507406874 ...........................................")
            cv_logger.debug("The eFUSE Write Disabled Shall be called post PubKeyHash Programming Automatically .........................................")




    '''
    Modify  : self, sends CRC Write command via JTAG
    Input   : test_program -- True for virtual write, False otherwise
              success -- checks if cthe command is successful or not
    Output  : lcoal_respond -- the respond packet of the sdm command
    '''
    def efuse_crc_write(self, test_program=True, success=True):
        acds_version = os.environ['QUARTUS_VERSION']
        cv_logger.info("Send CRC write")
        try:
            if (compare_quartus_version(acds_version,'21.1') == -1):
                local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_CRC_WRITE'], 0x65537546, 0x00000000)
            else:
                local_respond = self.efuse_user_security_option_program(security_option_key='CRC_ENABLE', test_program=test_program, success=success)
            cv_logger.info("Send CRC Write :: Response " + str(local_respond))
        except Exception as e:
            if success:
                assert_err(0, "ERROR :: CRC Write command failed")
            else:
                cv_logger.info("CRC Write Command failed as EXPECTED")

        return local_respond


    '''
    Modify  : self, read user defined fuses via sdm mbx command through JTAG. Device owner can use this command to read these fuses.
    Input   :
              row -- the efuse row, range [0-31]
              num_row -- number of rows to be read (each row is 32-bit), range [1-32]
              success -- checks if cthe command is successful or not
    Output  : response -- the respond packet of the sdm command
    '''
    def efuse_read_user_defined_fuses(self, row, num_row, success=True):
        cv_logger.info("EFUSE_READ_USER_DEFINED_FUSES")
        flag = 0
        reserve = 0
        # reserve field at position [31:16]
        flag = flag | (reserve << 16)
        flag = flag | ((num_row << 8) | (row))
        try:
            response=[]
            cv_logger.info("Send efuse_read_user_defined_fuses --flag check %s" %flag)
            response = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_READ_USER_DEFINED_FUSES'], flag)
        except Exception as e:
            if success:
                assert_err(0, "ERROR :: efuse_read_user_defined_fuses command failed")
            else:
                cv_logger.info("efuse_read_user_defined_fuses Command failed as EXPECTED")

        return response[1:]


    '''
    Modify  : self, write user defined fuses via sdm mbx command through JTAG. Device owner can use this command to program these fuses.
    Input   :
              bank -- the efuse bank, user define fuse at bank 3 for ND and bank 5 for agilex
              row -- the efuse row, range [0-31]
              num_row -- number of rows to be read (each row is 32-bit), range [1-32]
              values -- list of values for the fuse to be written, each element is a row
              check_before -- True if want to read fuse before write, False to skip
              check_after -- True if want to read fuse after write, False to skip
              success -- checks if cthe command is successful or not
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def efuse_user_defined_fuses_program(self, row, values, num_row, success=True, test_program=True, check_before=True, check_after=True, ast=0, skip_same=True):
        cv_logger.info("EFUSE_USER_DEFINED_FUSES_PROGRAM")
        flag = 0
        reserve = 0
        if test_program:
            flag = flag | (1 << 31)
        # reserve field at position [30:16]
        flag = flag | (reserve << 16)
        for value in values:
            assert_err(value >= 0 and value <= 0xffffffff, "ERROR :: Given value for a row is %d, which is outside of 32-bits" %value)
        # reserve field at position [30:16]
        flag = flag | (reserve << 16)
        flag = flag | ((num_row << 8) | (row))

        #assume the fuse values were 0 before writing them
        before_values = [0] * len(values)
        # if check_before, read user efuse before write
        if check_before:
            before_values = self.efuse_read_user_defined_fuses(row=row, num_row=len(values) ,success=True)
            for fuse in before_values:
                if fuse != 0:
                    cv_logger.warning("The fuse is already written!")
                    break

        #update the expectations of values for fuses
        exp_values = []
        if success:
            for i in range(len(values)):
                exp_values.append( before_values[i] | values[i] )

            if exp_values != values:
                cv_logger.warning("Since the fuse is already written, the result after your fuse virtual write may be different than your write value")

            if skip_same and exp_values == before_values:
                cv_logger.info("Skipping virtual write because all the fuse we are writing, has already been written.")
                return

        try:
            local_respond=[]
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_USER_DEFINED_FUSES_PROGRAM'], 0x55736572, flag, *values)

        except Exception as e:
            if success:
                assert_err(0, "ERROR :: efuse_user_defined_fuses_program command failed")
            else:
                cv_logger.info("efuse_user_defined_fuses_program Command failed as EXPECTED")

        #if check, get the actual fuse values after writing
        after_values = [0] * len(values)
        #read user efuse after write
        if check_after:
            after_values = self.efuse_read_user_defined_fuses(row=row, num_row=num_row ,success=True)
            if success and (after_values != exp_values):
                cv_logger.error("Expected virtual write to succeed with correct value")
                assert_err(not ast, "ERROR :: expected values %s, measured values %s" %(exp_values, after_values))
            if not success and (after_values != before_values):
                cv_logger.error("Expected virtual write to fail with unchanged fuse")
                assert_err(not ast, "ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))

        cv_logger.info("------------------------Response check here-------------------------------")
        if check_before:
            cv_logger.info(" Read fuse before write, row %s - read fuse value %s " %(row, before_values))
        cv_logger.info("Program fuses, num_row %d, row %d, with %s --flag check %s" %(num_row, row, values, flag))
        cv_logger.info("Send efuse_user_defined_fuses_program :: Response " + str(local_respond))
        if check_after:
            cv_logger.info(" Read fuse after write, row %s - read fuse value: %s, expected values: %s" %(row, after_values, exp_values))
        cv_logger.info("--------------------------------------------------------------------------")


        return local_respond


    '''
    Input   : bank -- the efuse bank
              row -- the efuse row
              num_row -- number of rows to be read (each row is 32-bit)
              success -- whether the read is successful or not, default True
              exp_values -- array of expected values for the read, only check if success is True
                            if None, no checking done, default None
              exp_err -- the expected error code if read fail, default to "dc", which means it can take any error code
              ast -- whether assertion is enabled for the checking of value after reading
    Mod     : self -- sends efuse_read command to read the specified rows
    Output  : an array of the efuse rows
    Example : efuse_read(bank=0, row=1, num_row=3)
              will return [bank 0 row 1, row 2, row 3]
    '''
    def efuse_read(self, bank, row, num_row, success=True, exp_values=None, ast=0, exp_err="dc"):
        cv_logger.info("EFUSE_READ bank %d, row %d, for %d rows" %(bank, row, num_row))
        addr = (bank << 11) | (row << 5)
        input_length = 2
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = SDM_CMD['EFUSE_READ']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        resp = self.jtag.packet_send_cmd(32, header, addr, num_row)
        cv_logger.info("Read %s with header %s" %(resp[1:], resp[0]))

        exp_length = num_row if success else 0
        if (exp_err == "dc") and (not success):
            #check length
            assert_err(len(resp) == 1 + exp_length, "ERROR :: Length of command respond is %d, expected %d" %(len(resp), 1 + exp_length))
            #check error code is not zero
            assert_err(resp[0] & 0x3FF != 0 , "ERROR :: Error code is 0, expected non-zero")
        else:
            exp_error = 0 if success else exp_err
            exp_header = exp_error | (exp_length << 12) | (input_id << 24) | (input_client << 28)
            assert_err(len(resp) == 1 + exp_length, "ERROR :: Length of command respond is %d, expected %d" %(len(resp), 1 + exp_length))
            assert_err(resp[0] == exp_header, "ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))

        if success and exp_values != None:
            if exp_values != resp[1:]:
                assert_err(not ast, "ERROR :: Expected values %s, different than read value above" %exp_values)
                print_err("ERROR :: Expected values %s, different than read value above" %exp_values)
            else:
                cv_logger.info("Read value same as expectation")

        return resp[1:]


    '''
    Input   : bank -- the efuse bank
              row -- the efuse row
              values -- list of values for the fuse to be written, each element is a row
              success -- True if expect the write to succeed, False otherwise
              check -- reads the fuse values before and after write, verify that the fuse
                       value after write is (before_write | write_value)
              read_success -- (for check) True if expect the read to succeed, False otherwise
              no_gap -- if we attempt to write gap fuse, the function will unset those write values
              no_security -- if we attempt to write security fuse, the function will unset those write values
              skip_zero -- if True, when ALL values are zero, the function will skip sending the write command
              skip_same -- if True, when the command will not change any fuse value, the function will skip sending the command
              ast -- whether assertion is enabled for the checking of value after writing
              exp_err -- if expected to fail, input the expected error code (default is "dc", which means can accept any error)
    Mod     : self -- sends efuse_test_write command to VIRTUALLY write the specified rows
    Example : efuse_virtual_write(bank=0, row=1, values=[0x3, 0x4) means:
              bank 0 row 1 virtual write 0x3
              bank 0 row 2 virtual write 0x4
    '''
    def efuse_virtual_write(self, bank, row, values, success=True, read_success=True, no_gap=False, no_security=False, skip_zero=False, skip_same=True, check=0, ast=0, exp_err="dc"):
        cv_logger.info("")
        for value in values:
            assert_err(value >= 0 and value <= 0xffffffff, "ERROR :: Given value for a row is %d, which is outside of 32-bits" %value)

        #unset the bits that are gap fuses if no_gap
        if no_gap:
            cv_logger.info("Detecting gap fuses and unset any writes for them")
            #for each row we are writing
            for i in range(len(values)):
                local_row = row + i
                for region in EFUSE["GAP"]:
                    #if we have passed the bank we are writing, just end the loop
                    if region[0] > bank:
                        break
                    #if there is gap fuse, don't write them
                    if region[0]==bank and region[1]==local_row:
                        num_bit = region[3] - region[2] + 1
                        mask = ~(((pow(2,num_bit) - 1) << region[2]) | ~(0xffffffff))
                        values[i] = values[i] & mask

        #unset the bits that are security fuses if no_security
        if no_security:
            cv_logger.info("Detecting gap fuses and unset any writes for them")
            #for each row we are writing
            for i in range(len(values)):
                local_row = row + i
                for region in EFUSE["SECURITY"]:
                    #if we have passed the bank we are writing, just end the loop
                    if region[0] > bank:
                        break
                    #if there is gap fuse, don't write them
                    if region[0]==bank and region[1]==local_row:
                        num_bit = region[3] - region[2] + 1
                        mask = ~(((pow(2,num_bit) - 1) << region[2]) | ~(0xffffffff))
                        values[i] = values[i] & mask

        all_zero = True
        for value in values:
            if value != 0:
                all_zero = False
                break
        if all_zero:
            cv_logger.warning("All the write values are zero, so no write will actually happen")
            if skip_zero:
                cv_logger.info("Skipping write for {bank %d; row %d} as specified by user for zero values" %(bank, row))
                return

        #assume the fuse values were 0 before writing them
        before_values = [0] * len(values)

        #if check, get the actual fuse values before writing
        if check:
            cv_logger.info("Reading the fuses before writing them")
            before_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)
            for fuse in before_values:
                if fuse != 0:
                    cv_logger.warning("The fuse is already written!")
                    break

        #update the expectations of values for after writing fuses
        exp_values = []
        if success:
            for i in range(len(values)):
                exp_values.append( before_values[i] | values[i] )

            if exp_values != values:
                cv_logger.warning("Since the fuse is already written, the result after your fuse virtual write may be different than your write value")

            if skip_same and exp_values == before_values:
                cv_logger.info("Skipping virtual write because all the fuse we are writing, has already been written.")
                return

        cv_logger.info("virtual write bank %d, row %d, with %s..." %(bank, row, values))

        addr = (bank << 11) | (row << 5)
        input_length = len(values) + 2 #0x65537546, addr, and the fuse values
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = SDM_CMD['EFUSE_TEST_WRITE']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        resp = self.jtag.packet_send_cmd(32, header, 0x65537546, addr, *values)
        cv_logger.info("EFUSE_TEST_WRITE respond %s" %resp)

        exp_length = 0
        assert_err(len(resp) == 1, "ERROR :: Length of respond is %d, expected 1" %len(resp))

        if (exp_err == "dc") and (not success):
            if resp[0] & 0x3FF == 0:
                assert_err(not ast, "ERROR :: The error code is 0, expected non-zero")
                print_err("ERROR :: The error code is 0, expected non-zero")
        else:
            exp_error = 0 if success else exp_err
            exp_header = exp_error | (exp_length << 12) | (input_id << 24) | (input_client << 28)
            if resp[0] != exp_header:
                assert_err(not ast, "ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))
                print_err("ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))


        #if check, get the actual fuse values after writing
        after_values = [0] * len(values)
        if check:
            cv_logger.info("Reading the fuses after writing them")
            after_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)

            if success and (after_values != exp_values):
                cv_logger.error("Expected virtual write to succeed with correct value")
                assert_err(not ast, "ERROR :: expected values %s, measured values %s" %(exp_values, after_values))
                print_err("ERROR :: expected values %s, measured values %s" %(exp_values, after_values))

            if not success and (after_values != before_values):
                cv_logger.error("Expected virtual write to fail with unchanged fuse")
                assert_err(not ast, "ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))
                print_err("ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))

    '''
    Require : efuse_write_disable() must have been run
    IMP!!   : Please use efuse_virtual_write instead to prevent yourself from
              physically blowing fuses. I (Yi Zhi) am using this to test command
              specific interlocks

    Same as efuse_virtual_write, but for actual write instead of virtual
    Please see efuse_virtual_write function header
    '''
    def efuse_write(self, bank, row, values, success=True, read_success=True, no_gap=False, no_security=False, skip_zero=False, skip_same=True, check=0, ast=0, exp_err="dc"):
        cv_logger.info("")
        assert_err(self._fuse_write_disabled, "ERROR :: You did not disable efuse write. Please do so before using efuse_write cmd, or you will blow the fuse")

        for value in values:
            assert_err(value >= 0 and value <= 0xffffffff, "ERROR :: Given value for a row is %d, which is outside of 32-bits" %value)

        #unset the bits that are gap fuses if no_gap
        if no_gap:
            cv_logger.info("Detecting gap fuses and unset any writes for them")
            #for each row we are writing
            for i in range(len(values)):
                local_row = row + i
                for region in EFUSE["GAP"]:
                    #if we have passed the bank we are writing, just end the loop
                    if region[0] > bank:
                        break
                    #if there is gap fuse, don't write them
                    if region[0]==bank and region[1]==local_row:
                        num_bit = region[3] - region[2] + 1
                        mask = ~(((pow(2,num_bit) - 1) << region[2]) | ~(0xffffffff))
                        values[i] = values[i] & mask

        #unset the bits that are security fuses if no_security
        if no_security:
            cv_logger.info("Detecting gap fuses and unset any writes for them")
            #for each row we are writing
            for i in range(len(values)):
                local_row = row + i
                for region in EFUSE["SECURITY"]:
                    #if we have passed the bank we are writing, just end the loop
                    if region[0] > bank:
                        break
                    #if there is gap fuse, don't write them
                    if region[0]==bank and region[1]==local_row:
                        num_bit = region[3] - region[2] + 1
                        mask = ~(((pow(2,num_bit) - 1) << region[2]) | ~(0xffffffff))
                        values[i] = values[i] & mask

        #checks if all values are zero, if they are, then should succeed (because no write will be done)
        all_zero = True
        for value in values:
            if value != 0:
                all_zero = False
                break
        if all_zero:
            cv_logger.warning("All the write values are zero, so no write will actually happen")
            if skip_zero:
                cv_logger.info("Skipping write for {bank %d; row %d} as specified by user for zero values" %(bank, row))
                return

        #assume the fuse values were 0 before writing them
        before_values = [0] * len(values)

        #if check, get the actual fuse values before writing
        if check:
            cv_logger.info("Reading the fuses before writing them")
            before_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)
            for fuse in before_values:
                if fuse != 0:
                    cv_logger.warning("The fuse is already written!")
                    break

        #update the expectations of values for after writing fuses
        exp_values = []
        if success:
            for i in range(len(values)):
                exp_values.append( before_values[i] | values[i] )

            if exp_values != values:
                cv_logger.warning("Since the fuse is already written, the result after your fuse write may be different than your write value")

            if skip_same and exp_values == before_values:
                cv_logger.info("Skipping write because all the fuse we are writing, has already been written.")
                return

        cv_logger.info("write bank %d, row %d, with %s..." %(bank, row, values))

        addr = (bank << 11) | (row << 5)
        input_length = len(values) + 2 #0x65537546, addr, and the fuse values
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = SDM_CMD['EFUSE_WRITE']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        resp = self.jtag.packet_send_cmd(32, header, 0x65537546, addr, *values)
        cv_logger.info("EFUSE_WRITE done with resp %s" %resp)

        exp_length = 0
        exp_error = 0 if success else exp_err

        if (exp_err == "dc") and (not success):
            if resp[0] & 0x3FF == 0:
                assert_err(not ast, "ERROR :: The error code is 0, expected non-zero")
                print_err("ERROR :: The error code is 0, expected non-zero")
        else:
            exp_error = 0 if success else exp_err
            exp_header = exp_error | (exp_length << 12) | (input_id << 24) | (input_client << 28)
            if resp[0] != exp_header:
                assert_err(not ast, "ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))
                print_err("ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))

        #if check, get the actual fuse values after writing
        after_values = [0] * len(values)
        if check:
            cv_logger.info("Reading the fuses after writing them")
            after_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)

            if success and (after_values != exp_values):
                cv_logger.error("Expected write to succeed with correct value")
                assert_err(not ast, "ERROR :: expected values %s, measured values %s" %(exp_values, after_values))
                print_err("ERROR :: expected values %s, measured values %s" %(exp_values, after_values))

            if not success and (after_values != before_values):
                cv_logger.error("Expected write to fail with unchanged fuse")
                assert_err(not ast, "ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))
                print_err("ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))

    '''
    Modify  : self, sends the efuse_reload_cache sdm command via jtag
    '''
    def efuse_reload_cache(self, ast=0):
        cv_logger.info("")
        input_length = 0
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = SDM_CMD['EFUSE_RELOAD_CACHE']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        cv_logger.info("Send EFUSE_RELOAD_CACHE")
        resp = self.jtag.packet_send_cmd(32, header)

        exp_length = 0
        exp_error = 0
        exp_header = exp_error | (exp_length << 12) | (input_id << 24) | (input_client << 28)
        assert_err(len(resp) == 1, "ERROR :: Length of respond is %d, expected 1" %len(resp))
        if resp[0] != exp_header:
            assert_err(not ast, "ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))
            print_err("ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))

        # reset internal prov_status scoreboard
        self.exp_prov_status = self.exp_prov_status_backup.copy()
        self._scoreboard_state = self._scoreboard_state_backup.copy()
        cv_logger.info("EFUSE_RELOAD_CACHE sent")


    '''
    Modify  : self, sends the efuse_status sdm command via jtag
    Output  : a list with num redundancy rows in [bank0, bank1, bank2, bank3]
    '''
    def efuse_status(self, ast=0):
        cv_logger.info("")
        input_length = 0
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = SDM_CMD['EFUSE_STATUS']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        cv_logger.info("Send EFUSE_STATUS")
        resp = self.jtag.packet_send_cmd(32, header)

        exp_length = 1
        exp_error = 0
        exp_header = exp_error | (exp_length << 12) | (input_id << 24) | (input_client << 28)
        cv_logger.info(resp)
        assert_err(len(resp) == 2, "ERROR :: Length of respond is %d, expected 2" %len(resp))
        if resp[0] != exp_header:
            assert_err(not ast, "ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))
            print_err("ERROR :: The given respond header is %d, expected %d" %(resp[0], exp_header))
        cv_logger.info("EFUSE_STATUS sent")
        return [resp[1] & 0xFF, (resp[1] >> 8) & 0xFF, (resp[1] >> 16) & 0xFF, (resp[1] >> 24) & 0xFF]


    '''
    Modify  : self, sends the efuse_pubkey_program sdm command via jtag
    Input   : type_of_hash -- "secp256r1" or "secp384r1"
                              also can pass in integer to set the bits directly, but make sure it is within [0,0xFF]
              test_program -- True for virtual write, False otherwise
              user_root_hash -- A list of the user root key hash, where each element is 4 bytes
              success -- Checks if the command is successful or not, True if the command shound respond with no error code, False if command should respond with error code.
              reserve -- values to put onto the reserve bits, must be within [0, 16383] <- now there are 14 bits of reserve bits (b29:16). this could change in the future.
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def efuse_pubkey_program(self, type_of_hash, test_program, user_root_hash, success=True, reserve=0, late_prov=False):
        cv_logger.info("EFUSE_PUBKEY_PROGRAM")
        flag = 0
        user_root_hash_count = 0
        if type_of_hash == "secp256r1":
            flag = 1
        elif type_of_hash == "secp384r1":
            flag = 2
            user_root_hash_count = (len(user_root_hash)/12)-1
        elif isinstance(type_of_hash, (int, long)) and type_of_hash >= 0 and type_of_hash <= 0xff:
            flag = type_of_hash
        else:
            assert_err(0, "ERROR :: Invalid type_of_hash %s" %type_of_hash)

        if test_program:
            flag = flag | (1 << 31)
        elif not self._fuse_write_disabled==True:
            assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE not called before attempting real EFUSE_PUBKEY_PROGRAM, failing test to prevent permanently altering the device")

        if "ND" in self._BASE_DIE.upper():
            if reserve > 16383 or reserve < 0:
                # reserve field bit range [29:16]
                assert_err(0, "ERROR :: Invalid reserve bit value %s" %reserve)
        else:
            if reserve > 8191 or reserve < 0:
                # reserve field bit range [28:16]
                assert_err(0, "ERROR :: Invalid reserve bit value %s" %reserve)

        # hsd:1507979713 move S flag from position 8 to 30
        # SV not using s_flag. put here for reference.
        # flag = flag | (s_flag << 30)
        # reserve field at position [29:16]
        flag = flag | (reserve << 16)


        # hsd:16011066834 0->1user,1->2users,2->3users
        # number of hashes at position [15:8]
        flag = flag | (int(user_root_hash_count) << 8)

        # late provisioning on bit-29
        cv_logger.info("Late Provisioning::[%s]" % (late_prov != 0))
        if late_prov :
            flag = flag | (1 << 29)

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_PUBKEY_PROGRAM'], 0x65537546, flag, *user_root_hash)


        cv_logger.info("EFUSE_PUBKEY_PROGRAM sent with flag %s (%s), with return packet of %s (%s)" %(flag, get_hex(flag), local_respond, get_hex(local_respond)))

        if success and local_respond != [0x0]:
            print_err("ERROR :: Unexpected error respond by EFUSE_PUBKEY_PROGRAM")
        elif (not success) and (local_respond == [0x0]):
            print_err("ERROR :: No error respond by EFUSE_PUBKEY_PROGRAM, but test indicated it should have failed")

        return local_respond

    '''
    Modify  : self, sends the efuse_sec_owner_pubkey_program sdm command via jtag
    Input   : type_of_hash -- "secp384r1"
                              also can pass in integer to set the bits directly, but make sure it is within [0,0xFF]
              test_program -- True for virtual write, False otherwise
              user_root_hash -- A list of the PR user root key hash, where each element is 4 bytes
              success -- Checks if the command is successful or not, True if the command shound respond with no error code, False if command should respond with error code.
              reserve -- values to put onto the reserve bits, must be within [0, 2097152] <- now there are 21 bits of reserve bits (b30:10). this could change in the future.
              sec_owner_type -- secondary owner type includes ['pr', 'ext_auth'] or reserved value [2,3]
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def efuse_pr_pubkey_program(self, *args, **kwargs):
        cv_logger.warning("'efuse_pr_pubkey_program()' is deprecated. use 'efuse_sec_owner_pubkey_program()' instead")
        return efuse_sec_owner_pubkey_program(*args, **kwargs)
        
    def efuse_sec_owner_pubkey_program(self, type_of_hash, test_program, user_root_hash, success=True, reserve=0, sec_owner_type="pr"):
        cv_logger.info("EFUSE_SEC_OWNER_PUBKEY_PROGRAM")
        flag = 0

        if type_of_hash == "secp384r1":
            flag = 2
        elif isinstance(type_of_hash, (int, long)) and type_of_hash >= 0 and type_of_hash <= 0xff:
            flag = type_of_hash
        else:
            assert_err(0, "ERROR :: Invalid type_of_hash %s" %type_of_hash)
        
        # VAB spec chapter 1.11.3 bit [9:8]
        sec_owner_map = {   "pr" : 0,
                            "ext_auth" : 1,
                            2 : 2,
                            3 : 3, }
        sec_owner_value = sec_owner_map.get(sec_owner_type, None)
        assert_err(sec_owner_value is not None, "ERROR :: Invalid sec_owner_type '%s'" % sec_owner_type)
        flag = flag | (sec_owner_value << 8)

        if test_program:
            flag = flag | (1 << 31)
        elif not self._fuse_write_disabled==True:
            assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE not called before attempting real EFUSE_PUBKEY_PROGRAM, failing test to prevent permanently altering the device")

        # VAB spec chapter 1.11.3 reserve bit [30:10]
        if reserve >= 0 and reserve < (1<<21) :
            flag = flag | (reserve << 10)
        else:
            assert_err(0, "ERROR :: Invalid reserve bit value %s" %reserve)

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_SEC_OWNER_PUBKEY_PROGRAM'], flag, *user_root_hash)

        cv_logger.info("EFUSE_SEC_OWNER_PUBKEY_PROGRAM sent with flag %s (%s), with return packet of %s (%s)" %(flag, get_hex(flag), local_respond, get_hex(local_respond)))

        if success and local_respond != [0x0]:
            print_err("ERROR :: Unexpected error respond by EFUSE_SEC_OWNER_PUBKEY_PROGRAM")
        elif (not success) and (local_respond == [0x0]):
            print_err("ERROR :: No error respond by EFUSE_SEC_OWNER_PUBKEY_PROGRAM, but test indicated it should have failed")

        return local_respond

    '''
    Require : efuse_write_disable() must have been run
    Modify  : self, sends the efuse_aes_program sdm command via jtag
    Input   : type_of_key -- "user_key" for user AES root key, "psg_key" for PSG AES root key
              test_program -- True for virtual write, False otherwise
              key_value -- The key (user/psg) to be programmed
              success -- Checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code
              reserve -- values to put onto the reserve bits, must be within [0, 8388607] <- now there are 23 bits of reserve bits (b30:8). This could change in the future.
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def efuse_aes_program(self, type_of_key='user_key', test_program=1, key_value='', success=True, reserve=0):
        cv_logger.info("EFUSE_AES_PROGRAM")
        #if assert error here, cannot check whether test_program is functioning, whether is using real or virtual fusing because EFUSE_WRITE_DISABLE already true
        #assert_err(self._fuse_write_disabled, "ERROR :: You did not call EFUSE_WRITE_DISABLE. Please do so before using efuse_aes_program cmd, or you will blow the fuse")
        flag = 0

        if type_of_key == "user_key":
            flag_key_type = 0x0
        elif type_of_key == "psg_key":
            flag_key_type = 0x1
        else:
            assert_err(0, "ERROR :: Invalid type_of_key %s" %flag_key_type)

        if test_program: # TEST GAP: unable to check prior to FW signing because we have to send EFUSE_WRITE_DISABLE to virtually write user public key hash without cancelling the old key.
            flag = flag | (1 << 31)
        elif not self.fuse_write_disabled==True:
            assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE not called before attempting real EFUSE_AES_PROGRAM, failing test to prevent permanently altering the device")

        if reserve > 8388607 or reserve < 0:
            assert_err(0, "ERROR :: Invalid reserve bit value %s" %reserve)

        flag = flag | (flag_key_type << 0)
        flag = flag | (reserve << 8)


        local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_AES_PROGRAM'], 0x65537546, flag, *key_value)
        cv_logger.info("EFUSE_AES_PROGRAM sent with flag %s (%s), with return packet of %s (%s)" %(flag, get_hex(flag), local_respond, get_hex(local_respond)))


        if success and local_respond != [0x0]:
            print_err("ERROR :: Unexpected error respond by EFUSE_AES_PROGRAM")
        elif (not success) and (local_respond == [0x0]):
            print_err("ERROR :: No error respond by EFUSE_AES_PROGRAM, but test indicated it should have failed")

        return local_respond


    '''
    Modify  : self, reads the PSG cancellation, force_pki_select (user root key size), User PUBKEY fuses
              to see if efuse_pubkey_program was done correctly
    Input   : type_of_hash -- "secp256r1" or "secp384r1" or None (for not programmed)
              user_root_hash -- None (for not programmed) , OR
                                A list of the user root key hash, where each element is 4 bytes (32 bits)
              cancel -- whether or not the PUBKEY_PROGRAM will write cancellation fuse
                        if True, will check that the PSG cancellation fuse is written correctly based on spec (id 1 for ND, id 0 for FM)
                        if False, will check the PSG cancellation fuse is not written
              success -- whether EFUSE_PUBKEY_PROGRAM will success or not. If success, it will cancel the fuses, else nothing is blown
    '''
    def check_pubkey_program(self, type_of_hash, user_root_hash, cancel=None, success=True, ast=0):
        cv_logger.info("Checking fuse values after issuing EFUSE_PUBKEY_PROGRAM")
        err_msgs = []
        local_pass = True

        if self._fuse_write_disabled and cancel:
            assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE is called. This will prevent keys to be cancelled.")

        if cancel == None:
            cancel = False if self._fuse_write_disabled else True

        cv_logger.info("Checking PSG PUBLIC CANCELLATION FUSE")
        fuse_location = EfuseBankManager('psg_public_key_cancellation');
        row_27 = self.efuse_read(bank=fuse_location.bank, row=fuse_location.row, num_row=4, success=True)

        cv_logger.info("Checking FORCE_PKI_SELECT FUSE")
        fuse_location = EfuseBankManager('force_pki_select');
        row_37 = self.efuse_read(bank=fuse_location.bank, row=fuse_location.row, num_row=1, success=True)
        force_pki_sel = (row_37[0] >> 20) & 0b11111111
        cv_logger.info("Force PKI Select (User Root Key Size) Fuse is %s" %force_pki_sel)

        cv_logger.info("Checking USER PUBLIC KEY HASH FUSE")
        fuse_location = EfuseBankManager('user_public_key_hash_long_0');
        fused_root_hash = self.efuse_read(bank=fuse_location.bank, row=fuse_location.row, num_row=12)

        cv_logger.info("Checking USER PUBLIC KEY CANCELLATION FUSE")
        fuse_location = EfuseBankManager('user_public_key_cancellation');
        user_cancellation_fuse = self.efuse_read(bank=fuse_location.bank, row=fuse_location.row, num_row=4)

        # Check all fields
        if success:
            #Check PSG cancellation fuse value
            if cancel: #we cancel psg cancellation fuse
                exp_row_27 = self.get_cancelled_psg_key()
                if (self.is_as_device() == True):
                    if (re.search('[Nn][Dd]', self._BASE_DIE) != None):
                        exp_row_27 = 2 | exp_row_27 #If it is AS/SFE device then key 1 is physically cancelled in ND
                    else:
                        exp_row_27 = 1 | exp_row_27 #If it is AS/SFE device then key 0 is physically cancelled in FM
            else:
                if (self.is_as_device() == True):
                    exp_row_27 = 2 if self.DUT_FAMILY == "stratix10" else 1
                else:
                    exp_row_27 = 0

            #check force_pki_select and user pubkey values
            if type_of_hash == "secp256r1":
                exp_pki = 0xf
                #check the first 8 elements with given value, remaining should be zero
                user_root_hash = user_root_hash + [0]*4
            #check all 12 elements with given value of the user root hash
            elif type_of_hash == "secp384r1":
                exp_pki = 0xf0
            elif type_of_hash == None:
                exp_pki = 0x0
                #check all 12 elements with given value
                user_root_hash = [0]*12
            else:
                assert_err(0, "ERROR :: Invalid type_of_hash %s" %type_of_hash)
        else:
            if (self.is_as_device() == True):
                exp_row_27 = 2 if self.DUT_FAMILY == "stratix10" else 1
            else:
                exp_row_27 = 0
            exp_pki = 0x0
            user_root_hash = [0]*12

        if row_27[0] != exp_row_27:
            err_msgs.append("ERROR :: PSG_CANCELLATION_FUSE value mismatched Measured = 0x%x and Expected = 0x%x" %(row_27[0], exp_row_27))
            local_pass = False
        if force_pki_sel != exp_pki:
            err_msgs.append("ERROR :: FORCE_PKI_SELECT value mismatched Measured = 0x%x and Expected = 0x%x" %(force_pki_sel, exp_pki))
            local_pass = False
        if fused_root_hash != user_root_hash:
            err_msgs.append("ERROR :: USER_PUBLIC_KEY_HASH value mismatched Measured = %s and Expected = %s" %(fused_root_hash, user_root_hash))
            local_pass = False

        if err_msgs:
            for err in err_msgs:
                print_err(err)
            if ast:
                assert_err(0, "ERROR :: FUSE VALUE incorrect")
        else:
            cv_logger.info("Fuse value result same as expectation")

        return local_pass


    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write the aes_key_update fuse
    Input   : test_program -- True for virtual write, False otherwise
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              ast -- if True, asserts a failure when the efuse writing and checking failed.
    '''
    def write_aes_key_update(self, test_program=True, success=True, check=True, ast=0, virtual_write=True):
        cv_logger.info("Start writing and checking aes_key_update fuse")
        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['aes_key_update'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['aes_key_update'][1]
        WRITE_VALUE = 0xf << efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['aes_key_update'][2]

        # Check current version
        current_quartus_version = os.environ['QUARTUS_VERSION']

        if test_program:

            if ((compare_quartus_version(current_quartus_version, '21.1') ==0) or (compare_quartus_version(current_quartus_version, '21.1'))):

                cv_logger.info("using sdm cmd to enable security option bit")
                local_respond = self.efuse_user_security_option_program(security_option_key=['AES_KEY_UPDATE_MODE'], test_program=test_program, success=success)
            else:
                if virtual_write:
                    cv_logger.info("Using efuse virtual write to enable AES key update mode")
                    self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)

                else:
                    cv_logger.info("Using efuse write to enable AES key update mode")
                    self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)
        else:
            cv_logger.info("User disable aes key update mode")

        if (local_respond != [0x0]):
            cv_logger.error("AES_KEY_UPDATE_MODE response is not [0]!")
        elif (not success) and (local_respond == [0x0]):
            cv_logger.error("No error respond by AES_KEY_UPDATE_MODE, but test indicated it should have failed")

    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write the puf disable fuse
    Input   : test_program -- True for virtual write, False otherwise
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              ast -- if True, asserts a failure when the efuse writing and checking failed.
    '''
    def write_puf_key_dis(self, test_program=True, success=True, check=True, ast=0):
        cv_logger.info("Start writing and checking puf_key_dis fuse")
        cv_logger.info("Device is %s" %self.DUT_FAMILY)

        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['puf_key_disable'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['puf_key_disable'][1]
        WRITE_VALUE = 0xf << efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['puf_key_disable'][2]

        # Check current version
        current_quartus_version = os.environ['QUARTUS_VERSION']

        if test_program:

            if ((compare_quartus_version(current_quartus_version, '21.1') ==0) or (compare_quartus_version(current_quartus_version, '21.1'))):

                cv_logger.info("using sdm cmd to enable security option bit")
                local_respond = self.efuse_user_security_option_program(security_option_key=['PUF_AES_KEY_DISABLE'], test_program=test_program, success=success)
            else:
                if virtual_write:
                    cv_logger.info("Using efuse virtual write to enable AES key update mode")
                    self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)

                else:
                    cv_logger.info("Using efuse write to enable AES key update mode")
                    self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)
        else:
            cv_logger.info("User disable puf aes key")

        if (local_respond != [0x0]):
            cv_logger.error("PUF_AES_KEY_DISABLE response is not [0]!")
        elif (not success) and (local_respond == [0x0]):
            cv_logger.error("No error respond by PUF_AES_KEY_DISABLE, but test indicated it should have failed")

    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write to engineering fuse
    Input   : test_program -- True for virtual write, False otherwise
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              ast -- if True, asserts a failure when the efuse writing and checking failed.
    '''
    def write_engineering_fuses(self, test_program=True, success=True, check=True, ast=0):
        cv_logger.info("Start writing and checking EngineeringDev fuse")
        cv_logger.info("Device is %s" %self.DUT_FAMILY)

        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['engineering_device'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['engineering_device'][1]
        WRITE_VALUE = 0xf << efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['engineering_device'][2]

        if self.DUT_FAMILY == 'stratix10':
            if test_program:
                self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)
            else:
                if test_program == False:
                    cv_logger.info("test_program must not be FALSE! If intended please check fwval_lib")
                    self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)
                self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=[WRITE_VALUE], success=success, check=check, no_gap=True, ast=ast)
        else:
            cv_logger.info("The current device does not support writing to EngineeringDev fuse..")

    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write the joint_cmf fuse
    Input   : test_program -- True for virtual write, False otherwise
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              skip_same -- if True, when the command will not change any fuse value, the function will skip sending the command
              ast -- if True, asserts a failure when the efuse writing and checking failed.
    '''
    def write_joint_cmf(self, test_program, success=True, check=True, ast=0, skip_same=True):

        cv_logger.info("Start writing and checking joint cmf fuse")
        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['joint_cmf_pka'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['joint_cmf_pka'][1]
        WRITE_VALUE = [0xf << efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['joint_cmf_pka'][2]]

        # Check current version
        current_quartus_version = os.environ['QUARTUS_VERSION']

        if (((compare_quartus_version(current_quartus_version, '21.1') == 0) or (compare_quartus_version(current_quartus_version, '21.1') == 1))) :
            #assume the fuse values were 0 before writing them
            before_values = [0] * len(WRITE_VALUE)
            if check:
                cv_logger.info("Reading the fuses before writing them")
                before_values = self.efuse_read(bank=WRITE_BANK, row=WRITE_ROW, num_row=len(WRITE_VALUE), success=True)
                for fuse in before_values:
                    if fuse != 0:
                        cv_logger.warning("The fuse is already written!")
                        break
            # update the expectations of values for after writing fuses
            exp_values = []
            if success:
                # update COSIGN_STATUS
                self.update_prov_exp(cosign=1)

                for i in range(len(WRITE_VALUE)):
                    exp_values.append(before_values[i] | WRITE_VALUE[i])

                if exp_values != WRITE_VALUE:
                    cv_logger.warning("Since the fuse is already written, the result after your fuse virtual write may be different than your write value")

                if skip_same and exp_values == before_values:
                    cv_logger.info("Skipping virtual write because all the fuse we are writing, has already been written")
                    return
            self.efuse_user_security_option_program(security_option_key='FIRMWARE_JOINT_SIGNING', success=success, test_program=test_program)
            # if check, get the actual fuse value after writing
            if check:
                cv_logger.info("Reading the fuses after writing them")
                after_values = self.efuse_read(bank=WRITE_BANK, row=WRITE_ROW, num_row=len(WRITE_VALUE), success=True)

                if success and (after_values != exp_values):
                    cv_logger.error("Expected virtual write to succeed with correct value")
                    assert_err(not ast, "ERROR :: expected values %s, measured values %s" %(exp_values, after_values))
                    print_err("ERROR :: expected values %s, measured values %s" %(exp_values, after_values))

                if not success and (after_values != before_values):
                    cv_logger.error("Expected virtual write to fail with unchanged fuse")
                    assert_err(not ast, "ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))
                    print_err("ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))
        else:
            if test_program:
                self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=WRITE_VALUE, success=success, check=check, no_gap=True, ast=ast)
            else:
                self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=WRITE_VALUE, success=success, check=check, no_gap=True, ast=ast)

    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write the user cancellation fuse
    Input   : test_program -- True for virtual write, False otherwise
              cancel_id -- cancellation id to be cancelled, must be within [0,31]
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              exp_err -- if expected to fail, input the expected error code (default is "dc", which means can accept any error)
    '''
    def write_user_cancellation(self, test_program, cancel_id, success=True, check=True, exp_err="dc", signing_pem="", signing_qky="", output_ccert="output_test.ccert"):
        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['user_public_key_cancellation'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['user_public_key_cancellation'][1]

        cv_logger.info("Start writing and checking user cancellation fuse")

        assert_err(cancel_id >=0 and cancel_id <= 31, "ERROR :: Invalid cancellation ID. Should be within [0,31]")

        bit_offset1 = cancel_id % 32
        bit_offset2 = (bit_offset1 + 4) % 32
        bit_offset3 = (bit_offset2 + 2) % 32
        bit_offset4 = (bit_offset3 + 2) % 32

        # Check current version
        current_quartus_version = os.environ['QUARTUS_VERSION']

        # Cancel Type
        cancel_type = "CANCEL_OWNER_KEY"

        if (compare_quartus_version(current_quartus_version, '21.1') == 0 or compare_quartus_version(current_quartus_version, '21.1')):
            try:
                checks = []

                # Test Program
                cv_logger.info("test_program does not matter for CCERT EXPLICIT CANCELLATION flow - the test flag is always set to true")

                if check:
                    # Check the efuse values before blowing
                    before_values = self.check_cancellation_before(cancel_id=cancel_id, cancel_type=cancel_type)

                # Initialize testOBJ
                testOBJ = SecurityDataTypes('AUTH_TEST')
                testOBJ.HANDLES['DUT']=self.dut
                testOBJ.configuration_source = "jtag"

                # Blow the cancellation
                error = testOBJ.ccert_explicit_cancel(dutHANDLE=self, ccert_type=cancel_type, cancel_key=cancel_id,
                                                      signing_pem=signing_pem, signing_qky=signing_qky, send_type="programmer",
                                                      success=success, output_ccert=output_ccert)
                checks.append(error)

                if check:
                    # Check the efuse values after blowing
                    self.check_cancellation_after(cancel_id=cancel_id, before_values=before_values, success=success, cancel_type=cancel_type)

                # Check for failure
                for checking in checks:
                    if(checking == False):
                        print_err("ERROR :: FUNCTION WRITE_USER_KEY_CANCELLATION FAILED")
                        assert_err(0, "ERROR :: FAILED TO CANCEL USER KEY EXPLICITLY WITH CCERT FLOW")

            except Exception as e:
                print_err("ERROR :: EXCEPTION OCCURED IN WRITE_USER_KEY_CANCELLATION %s" %e)
                assert_err(0, "ERROR :: FAILED TO CANCEL USER KEY EXPLICITLY WITH CCERT FLOW")
        else:
            if test_program:
                self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4], success=success, check=check, no_gap=True, exp_err=exp_err)
            else:
                self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4], success=success, check=check, no_gap=True, exp_err=exp_err)


    '''
    Modify  : self, sends the efuse_write or efuse_test_write sdm command via jtag to write the psg cancellation fuse
    Input   : test_program -- True for virtual write, False otherwise
              cancel_id -- cancellation id to be cancelled, must be within [0,31]
              success -- Whether the user expects this write to success or not
              check -- If True, checks the fuse value before and after writing
              exp_err -- if expected to fail, input the expected error code (default is "dc", which means can accept any error)
    '''
    def write_psg_cancellation(self, test_program, cancel_id, success=True, check=True, exp_err="dc", signing_pem="", signing_qky="", output_ccert="output_test.ccert"):
        WRITE_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['psg_public_key_cancellation'][0]
        WRITE_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['psg_public_key_cancellation'][1]

        cv_logger.info("Start writing and checking PSG cancellation fuse for id #%d" %cancel_id)

        assert_err(cancel_id >=0 and cancel_id <= 31, "ERROR :: Invalid cancellation ID. Should be within [0,31]")

        bit_offset1 = cancel_id % 32
        bit_offset2 = (bit_offset1 + 4) % 32
        bit_offset3 = (bit_offset2 + 2) % 32
        bit_offset4 = (bit_offset3 + 2) % 32

        # Check current version
        current_quartus_version = os.environ['QUARTUS_VERSION']

        # Cancel Type
        cancel_type = "CANCEL_INTEL_KEY"

        if ((compare_quartus_version(current_quartus_version, '21.1') == 0) or (compare_quartus_version(current_quartus_version, '21.1') == 1)):
            try:
                checks = []

                # Test Program
                cv_logger.info("test_program does not matter for CCERT EXPLICIT CANCELLATION flow - the test flag is always set to true")

                if check:
                    # Check the efuse values before blowing
                    before_values = self.check_cancellation_before(cancel_id=cancel_id, cancel_type=cancel_type)

                # Initialize testOBJ
                testOBJ = SecurityDataTypes('AUTH_TEST')
                testOBJ.HANDLES['DUT']=self.dut
                testOBJ.configuration_source = "jtag"

                # Blow the cancellation
                error = testOBJ.ccert_explicit_cancel(dutHANDLE=self, ccert_type=cancel_type, cancel_key=cancel_id,
                                                      signing_pem=signing_pem, signing_qky=signing_qky, send_type="programmer", success=success, output_ccert=output_ccert)
                checks.append(error)

                if check:
                    # Check the efuse values after blowing
                    self.check_cancellation_after(cancel_id=cancel_id, before_values=before_values, success=success, cancel_type=cancel_type)

                # Check for failure
                for checking in checks:
                    if(checking == False):
                        print_err("ERROR :: FUNCTION WRITE_PSG_CANCELLATION FAILED")
                        assert_err(0, "ERROR :: FAILED TO CANCEL PSG KEY EXPLICITLY WITH CCERT FLOW")

            except Exception as e:
                print_err("ERROR :: EXCEPTION OCCURED IN WRITE_PSG_CANCELLATION %s" %e)
                assert_err(0, "ERROR :: FAILED TO CANCEL PSG KEY EXPLICITLY WITH CCERT FLOW")
        else:
            if test_program:
                self.efuse_virtual_write(bank=WRITE_BANK, row=WRITE_ROW, values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4], success=success, check=check, no_gap=True, exp_err=exp_err)
            else:
                self.efuse_write(bank=WRITE_BANK, row=WRITE_ROW, values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4], success=success, check=check, no_gap=True, exp_err=exp_err)

    '''
    Modify  : self, checks efuses after writing
    Input   : cancel_id -- the cancel id
    Output  : before_values -- values as read from efuse before writing
    '''
    def check_cancellation_before(self, cancel_id="", cancel_type=""):

        read_success = True

        ast = 0

        if cancel_type == "CANCEL_INTEL_KEY":
            key_var = 'psg_public_key_cancellation'
        elif cancel_type == "CANCEL_OWNER_KEY":
            key_var = 'user_public_key_cancellation'
        else:
            cv_logger.info("no cancel_type selected, defaulting to user key cancellation")
            key_var = 'user_public_key_cancellation'

        bank = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][0]
        row  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][1]

        # Offset to 4 copies of key cancellation value in efuse (please refer to efuse document)
        bit_offset1 = cancel_id % 32
        bit_offset2 = (bit_offset1 + 4) % 32
        bit_offset3 = (bit_offset2 + 2) % 32
        bit_offset4 = (bit_offset3 + 2) % 32

        values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4]

        #assume the fuse values were 0 before writing them
        before_values = [0] * len(values)

        #if check, get the actual fuse values before writing
        cv_logger.info("Reading the fuses before writing them")
        before_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)
        for fuse in before_values:
            if fuse != 0:
                cv_logger.warning("The fuse is already written!")
                break

        return before_values

    '''
    Modify  : self, checks efuses after writing
    Input   : cancel_id -- the cancel id
              before_values -- input taken from check_before
              success -- Checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code.
    Output  : N/A
    '''
    def check_cancellation_after(self, cancel_id="", before_values="", success=True, cancel_type=""):

        read_success = True

        ast = 0

        if cancel_type == "CANCEL_INTEL_KEY":
            key_var = 'psg_public_key_cancellation'
        elif cancel_type == "CANCEL_OWNER_KEY":
            key_var = 'user_public_key_cancellation'
        else:
            cv_logger.info("no cancel_type selected, defaulting to user key cancellation")
            key_var = 'user_public_key_cancellation'

        bank = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][0]
        row  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][1]

        # Offset to 4 copies of key cancellation value in efuse (please refer to efuse document)
        bit_offset1 = cancel_id % 32
        bit_offset2 = (bit_offset1 + 4) % 32
        bit_offset3 = (bit_offset2 + 2) % 32
        bit_offset4 = (bit_offset3 + 2) % 32

        values=[1 << bit_offset1, 1 << bit_offset2, 1 << bit_offset3, 1 << bit_offset4]

        #if check, get the actual fuse values after writing
        after_values = [0] * len(values)

        cv_logger.info("Reading the fuses after writing them")
        after_values = self.efuse_read(bank=bank, row=row, num_row=len(values), success=read_success)

        #update the expectations of values for after writing fuses
        exp_values = []
        if success:
            for i in range(len(values)):
                exp_values.append( before_values[i] | values[i] )

            if exp_values != values:
                cv_logger.warning("Since the fuse is already written, the result after your fuse virtual write may be different than your write value")

        print (before_values)
        print (after_values)

        if success and (after_values != exp_values):
            cv_logger.error("Expected virtual write to succeed with correct value")
            assert_err(not ast, "ERROR :: expected values %s, measured values %s" %(exp_values, after_values))
            print_err("ERROR :: expected values %s, measured values %s" %(exp_values, after_values))

        if not success and (after_values != before_values):
            cv_logger.error("Expected virtual write to fail with unchanged fuse")
            assert_err(not ast, "ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))
            print_err("ERROR :: expected (unchanged) values %s, measured values %s" %(before_values, after_values))

    '''
    Modify  : self, sends the efuse_pubkey_program sdm command via jtag
    Input   : qky -- input qky file
              test_program -- True for virtual write, False otherwise
              test_mode -- 0 for using real UDS value, 1-3 for using different set of fake UDS value
              success -- Checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code.
              reserve -- values to put onto the reserve bits, must be within [0, 16383] <- now there are 14 bits of reserve bits (b29:16). this could change in the future.
              owner -- [static, pr]. default is static, uses PUBKEY_PROGRAM. pr uses PR_PUBKEY_PROGRAM. for pr slot, it is always at last slot. slot position might change in the future.
              late_prov -- [True, False(default)] enable late provisioning for FM7 and beyond
    Output  : local_response -- the respond packet of the sdm command
    '''
    def qky_program(self, qky, fuse_info_txt="fuse.temp.txt", test_program=True, success=True, reserve=0, owner="static",test_mode=None, late_prov=False):

        # allowed owner type
        owner_types = ["static", "pr", "ext_auth"]
        assert_err(owner in owner_types, "ERROR :: Unknown owner type %s. Valid range:%s" % (owner, owner_types))
        assert_err(not ((owner == "pr") and late_prov), "ERROR :: VAB Multi Authority and Late Provisioning does not work together")
        # checker for 'ext_auth' bypassed to allow for negative test scenario where test deliberately pair ext_auth and late_prov together
        #assert_err(not ((owner == "ext_auth") and late_prov), "ERROR :: VAB Multi Authority and Late Provisioning does not work together")

        if success:
            # Check bootrom - Expected failed for Old bootROM - ND5 Rev C1 or older; ND4 Rev A
            if ( ((re.search('[Nn][Dd]5', self._BASE_DIE) != None) and (re.search('[aA]|[bB]|[cC][0|1]', self._REV) != None)) or ((re.search('[Nn][Dd]4', self._BASE_DIE) != None) and (re.search('[aA]', self._REV) != None))):
                cv_logger.warning("Detected device %s Rev %s" %(self._BASE_DIE, self._REV))
                cv_logger.error("Expected passed for older bootrom? Please check the test content")

        # convert qky back to str if it is single element qky list
        if isinstance(qky, list) and (len(qky) == 1) :
            qky = qky[0]

        root_hash = []
        if isinstance(qky, str) :
            root_hash = get_root_hash(qky=qky, fuse_info_txt=fuse_info_txt)

            # print root_hash
            cv_logger.info("qky={} root_hash={}".format(qky, ', '.join(hex(x) for x in root_hash)))

            # single qky and static always use first slot. occupied slot should not error out from lib
            # scenario - unprovisioned device
            if ((self.exp_prov_status['OWNER_RH0_CANC_STATUS'] == 0) and
                (self.exp_prov_status['OWNER_RH0'] == [0]) and
                (owner == "static") and success) :

                self.update_prov_exp(slot0_hash=root_hash)

                if not late_prov :
                    # unused slots are cancelled if late_prov is off
                    for slot in range(1,self.RH_SLOT_COUNT) :
                        self.update_prov_exp(**{"slot%d_status"%(slot):1})

            if ((self._scoreboard_state['secondary_ownership_pk'] == 0) and 
                ((owner == "pr") or (owner == "ext_auth")) and success and
                (self._scoreboard_state['sec_owner_auth_flag'] == 1)) :

                # if the final slot is cancelled, get the next available slot to be provisioned
                # final slot is from self.RH_SLOT_COUNT
                # next available slot need to search using for loop
                final_slot_canc_status = "OWNER_RH%s_CANC_STATUS" % (self.RH_SLOT_COUNT - 1)
                for slot in range(self.RH_SLOT_COUNT) :
                    owner_rh = "OWNER_RH%s" % (slot)
                    
                    if self.exp_prov_status[owner_rh] == [0] :
                        break
                        
                pr_rh_prov_done = self._scoreboard_state['pr_rh_prov_done']
                ext_auth_rh_prov_done = self._scoreboard_state['ext_auth_rh_prov_done']
                # swap slot(N)_hash with slot(N-1)_hash
                if ((pr_rh_prov_done==1) and
                    (ext_auth_rh_prov_done==0) and
                    (owner == "ext_auth") and
                    (slot == (self.RH_SLOT_COUNT-1))):
                    owner_rh_Nm1 = "OWNER_RH%s" % (slot-1)
                    # slot3 pr root hash copy to slot 4
                    self.exp_prov_status[owner_rh] = self.exp_prov_status.get(owner_rh_Nm1, [4242])
                    # hack slot to overwrite slot3 root hash later
                    slot -= 1
                    

                if (self.exp_prov_status[final_slot_canc_status] == 1) :
                    self.update_prov_exp(**{"slot%d_hash"%(slot):root_hash})

                    if slot != 0 :
                        self.update_prov_exp(hash_count=self.exp_prov_status['HASH_COUNT']+1)
                        self._scoreboard_state['secondary_ownership_pk'] = 1
                        
                        if owner == "pr":
                            self._scoreboard_state['pr_rh_prov_done'] = 1
                            
                        if owner == "ext_auth":
                            self._scoreboard_state['ext_auth_rh_prov_done'] = 1

        elif isinstance(qky, list) :
            # append root_hash here
            # receive qky in the form of string(path) list
            # missing fuse_info_txt should not error out
            assert_err(owner == "static", "ERROR :: Multiple QKY not supported for PR or EXT_AUTH")
            assert_err(len(qky) != 0, "ERROR :: QKY list is empty")

            # preprocess the fuse_info_txt
            if isinstance(fuse_info_txt, str):
                fuse_info_txt = [fuse_info_txt]
            # fill in the missing fuse_info_txt if needed to make qky and fuse_info_txt list same length
            for i in range(len(qky)-len(fuse_info_txt)) :
                fuse_info_txt.append("fuse.temp%d.txt" % (i))

            slot = 0
            for _qky, _fuse_info_txt in zip(qky, fuse_info_txt) :
                _root_hash = []
                _root_hash = get_root_hash(qky=_qky, fuse_info_txt=_fuse_info_txt)
                cv_logger.info("qky={} root_hash={}".format(_qky, ', '.join(hex(x) for x in _root_hash)))
                root_hash += _root_hash

                # update prov_data
                _owner_rh = "OWNER_RH%s" % (slot)
                _owner_rh_canc_status = "OWNER_RH%s_CANC_STATUS" % (slot)
                if self.exp_prov_status[_owner_rh] == [0] and self.exp_prov_status[_owner_rh_canc_status] == 0 and success:
                    self.update_prov_exp(**{"slot%d_hash"%(slot):_root_hash})
                    if slot != 0 :
                        self.update_prov_exp(hash_count=self.exp_prov_status['HASH_COUNT']+1)

                slot += 1


            # update unused slot cancellation status
            if not late_prov:
                for slot in range(self.RH_SLOT_COUNT) :
                    _owner_rh = "OWNER_RH%s" % (slot)

                    if ((slot >= len(qky)) and (self.exp_prov_status[_owner_rh] == [0]) and success):
                        self.update_prov_exp(**{"slot%d_status"%(slot):1})

        key_length = 12
        if len(root_hash) == 8 :
            hash_type = "secp256r1"
        # fm6 - <=36; fm7 going to be <=60
        elif len(root_hash) % key_length == 0 and len(root_hash) <= (key_length * self.RH_SLOT_COUNT):
            hash_type = "secp384r1"
        else:
            assert_err(0, "ERROR :: Unknown root_hash type, length of root_hash is %d " %len(root_hash))

        '---------------------------Check if the eFUSE Write Disabled is called - IF Skipped due to HSD#1507406874 --- Protect the device by forcing the test_program to set True-----------'
        if(self._fuse_write_disabled):
            #do virtual pubkey program
            if owner == "static" :
                qky_return = self.efuse_pubkey_program(type_of_hash=hash_type, test_program=test_program, user_root_hash=root_hash, success=success, reserve=reserve, late_prov=late_prov)
            else:
                qky_return = self.efuse_sec_owner_pubkey_program(type_of_hash=hash_type, test_program=test_program, user_root_hash=root_hash, success=success, reserve=reserve, sec_owner_type=owner)
            # psg_keys_cancel = False #If EFUSE_WRITE_DISABLED called, no key will be cancelled
        else:
            # psg_keys_cancel = True #If EFUSE_WRITE_DISABLED not called, keys will be cancelled
            if(not test_program):
                cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
                test_program = True

            '-------------Calling the eFuse Write Disabled followed by pubkey hash'
            if owner == "static" :
                qky_return = self.efuse_pubkey_program(type_of_hash=hash_type, test_program=test_program, user_root_hash=root_hash, success=success, reserve=reserve, late_prov=late_prov)
            else:
                qky_return = self.efuse_sec_owner_pubkey_program(type_of_hash=hash_type, test_program=test_program, user_root_hash=root_hash, success=success, reserve=reserve, sec_owner_type=owner)
            self.efuse_write_disable(skip_program=False, test_mode=test_mode)

        # self.check_pubkey_program(type_of_hash=hash_type, user_root_hash=root_hash, cancel=psg_keys_cancel, read_only=True)

        return qky_return




    '''
    Modify  : self, qek_program_mbx used to program the AES SYMMETRIC KEY to storage device selected
    Input   : key_storage -- key storage selection BBRAM, EFUSE
              type_of_key -- key source user or intel own
              test_program -- True for virtual write, False otherwise
              aes_password -- password storage file
              aes_key_qek -- The encryption symmetric key
              aes_key_output -- Content of the fuse in hex written in file
              success -- Checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code.
              reserve -- values to put onto the reserve bits, must be within [0, 8388607] <- now there are 23 bits of reserve bits (b30:8). this could change in the future.
    Output  : response -- the respond packet of the sdm command
    '''
    def qek_program_mbx(self, key_storage='BBRAM', type_of_key='user_key', aes_password='aes_passphrase.txt',  aes_key_qek='aes_key.qek', aes_key_output='aes_key_output.txt', test_program=1, success=True, reserve=0):

        try:
            '--Opening the password phrase file -------------------'
            aes_password_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__),aes_password))
            aes_key_qek_file_path  = os.path.abspath(os.path.join(os.path.dirname(__file__),aes_key_qek))
            aes_key_qek_op_path    = os.path.abspath(os.path.join(os.path.dirname(__file__),aes_key_output))

            '--------First Checking if the passed key storage is something valid------------------------------------'
            if(not ((key_storage.upper() == 'BBRAM') or (key_storage.upper() == 'EFUSE') or (key_storage.upper() == 'VEFUSE'))):
                cv_logger.error("TEST_OBJECT <> %s :: Invalid AES KEY STORAGE location passed -- %s" %(self.TEST_DESCRIPTOR_UNDER_RUN, key_storage.upper()))
                assert_err(0, "ERROR :: ERROR_INVALID_KEY_STORAGE_SENT " %key_storage.upper())

            '-------Extracting the aes key value that can be stored be programmed ----------------------------------'
            root_aes_key_txt = get_root_aes(passphrase=aes_password_file_path, qek=aes_key_qek_file_path, aes_root_txt=aes_key_qek_op_path)

            '---------Now programming the AES USER symmetric key----------------------------------------------------'
            if(key_storage.upper() == "EFUSE"):
                response = self.efuse_aes_program(type_of_key=type_of_key.lower(), key_value= root_aes_key_txt, test_program=test_program, success=success, reserve=reserve)
            elif(key_storage.upper() == "BBRAM"):
                response = self.jtag_volatile_aes_write(root_aes_key_txt, success=success)
            else:
                assert_err(0, "ERROR :: ERROR_EFUSE_AES_KEY_STORAGE_INVALID %s" %key_storage.upper())

            return response

        except TESTFAIL_HANDLER as err:
            return err.type
            
    '''
    Modify   : Send sdos ocs certificate
    Input    : ccert_file - sdos ccert file in .ccert format
               test_program -- True for virtual write, False otherwise
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
    Output   : response -- the respond packet of the sdm command
    '''
    def send_sdos_ocs_ccert(self, ccert_file, test_program=True,success=True, exp_err=0):
        cv_logger.info("Sending SDOS OCS CCERT")
        security_datatype = SecurityDataTypes('BIT AUTH')

        # syscon will see ccert data loss in emulator
        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            try :
                # force syscon to release platform
                if self.dut.system_console != None :
                    self.dut.close_platform()
            except :
                pass

            try :
                return_msg = ""
                qpgm_cmd = "quartus_pgm -c%d -mJTAG -o\"p;%s\"" % (self.dut.dut_cable, ccert_file)
                return_msg = run_command(qpgm_cmd, timeout=120)
            except :
                if not success :
                    cv_logger.info("Failed to program sdos ccert as EXPECTED with respond: %s" %local_respond)
                else :
                    print_err("ERROR :: Failed to program sdos ccert UNEXPECTEDLY with respond: %s" %local_respond)

            if re.search("Error", return_msg) == None:
                local_respond = [0,0]

            if self.dut.system_console == None :
                self.dut.open_platform()

        else :
            cert_content = security_datatype.read_ccert(ccert_file)

            if not (self._fuse_write_disabled and test_program):
                cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
                test_program = True

            local_respond = self.jtag_send_certificate(cert_data=cert_content,
                                                       test_program=test_program,
                                                       success=success)

            if (len(local_respond) == 1) :
                # legacy FW response should be an error but not to cause out-of-index error
                print_err("Non-conformant response code: %s" % (local_respond))
                return local_respond[0]

            if (not success) and local_respond[1] != 0:
                cv_logger.info("Failed to program sdos ccert as EXPECTED with respond: %s" %local_respond)
                if exp_err:
                    assert_err(local_respond[1] == exp_err,
                        "ERROR :: ERROR value mismatched Measured = 0x%x and Expected = 0x%x" %(local_respond[1],exp_err))

            elif success and local_respond[1] != 0:
                print_err("ERROR :: Failed to program sdos ccert UNEXPECTEDLY with respond: %s" %local_respond)

        return local_respond[1]

    '''
    Modify   : Send cancellation certificate
    Input    : ccert_file - cancellation file in .ccert format
               test_program -- True for virtual write, False otherwise
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
    Output   : response -- the respond packet of the sdm command
    '''
    def send_cancellation_ccert(self, ccert_file, test_program=True,success=True, exp_err=0):
        cv_logger.info("Sending Cancellation CCERT")
        security_datatype = SecurityDataTypes('BIT AUTH')

        # syscon will see ccert data loss in emulator
        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            try :
                # force syscon to release platform
                if self.dut.system_console != None :
                    self.dut.close_platform()
            except :
                pass

            try :
                return_msg = ""
                qpgm_cmd = "quartus_pgm -c%d -mJTAG -o\"p;%s\"" % (self.dut.dut_cable, ccert_file)
                return_msg = run_command(qpgm_cmd, timeout=120)
            except :
                if not success :
                    cv_logger.info("Failed to program cancellation fuses as EXPECTED with respond: %s (%s)" % (local_respond, get_hex(local_respond)))
                else :
                    print_err("ERROR :: Failed to program cancellation fuses UNEXPECTEDLY with respond: %s (%s)" %(local_respond, get_hex(local_respond)))

            if re.search("Error", return_msg) == None:
                local_respond = [0,0]

            if self.dut.system_console == None :
                self.dut.open_platform()

        else :
            cert_content = security_datatype.read_ccert(ccert_file)

            if not (self._fuse_write_disabled and test_program):
                cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
                test_program = True

            local_respond = self.jtag_send_certificate(cert_data=cert_content,
                                                       test_program=test_program,
                                                       success=success)

            if (len(local_respond) == 1) :
                # legacy FW response should be an error but not to cause out-of-index error
                print_err("Non-conformant response code: %s" % (local_respond))
                return local_respond[0]

            if (not success) and local_respond[1] != 0:
                cv_logger.info("Failed to program cancellation fuses as EXPECTED with respond: %s (%s)" %(local_respond, get_hex(local_respond)))
                if exp_err:
                    assert_err(local_respond[1] == exp_err,
                        "ERROR :: ERROR value mismatched Measured = 0x%x and Expected = 0x%x" %(local_respond[1],exp_err))

            elif success and local_respond[1] != 0:
                print_err("ERROR :: Failed to program cancellation fuses UNEXPECTEDLY with respond: %s (%s)" %(local_respond, get_hex(local_respond)))

        return local_respond[1]
    '''
    Modify   : Send aes cancellation certificate
    Input    : ccert_file - input cancellation file in .ccert format
               key_storage -- BBRAM, OFF_CHIP
               qek_file -- .qek user AES key filename
               pem_file -- .pem user private key
               qky_file -- .qky file with sufficient permission (permission=64)
               ccert_device -- opn of the device
               cancel_all_keys -- 'on' to cancel all older aes key, else only cancel the input aes key
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
    Output   : response -- the respond packet of the sdm command
    '''
    def send_aes_cancel_cert(self, qek_file, qky_file, pem_file, password=None, key_storage="EFUSE", ccert_device=None, cancel_all_keys=None, option="programmer", success=True, ccert_file=None, debug_programmerhelper=False):

        # if didnt enter own certificate file
        if ccert_file == None:
            qek_filename = os.path.basename(qky_file)
            qek_filename = os.path.splitext(qek_filename)[0]
            ccert_file = "signed_user_aeskey_cancel_" + key_storage + "_" + qek_filename + ".ccert"
            
            # Generate signed user AES Key Cancellation Certificate
            gen_aes_cancel_cert(qek_file=qek_file, qky_file=qky_file, pem_file=pem_file, key_storage=key_storage,password=password,ccert_device=ccert_device, cancel_all_keys=cancel_all_keys, output_ccert_file=ccert_file)
        
        # send via sdm or programmer
        if option == "sdm":
            cv_logger.info("Send AES cancellation ccert by SDM command thru JTAG")
            security_datatype = SecurityDataTypes('AES KEY CANCEL')
            
            cert_content = security_datatype.read_ccert(ccert_file)

            cv_logger.info("Sending user AES Cancellation CCERT")

            if not (self._fuse_write_disabled and test_program):
                cv_logger.debug("Efuse Write Disable is not call, calling the command to protect the device ........................")
                self.efuse_write_disable(skip_program=False,test_mode=test_mode)

            local_respond = self.jtag_send_certificate(cert_data=cert_content,test_program=0, success=success)
                    
        # read responed and determine success or not
        elif option == 'programmer':
            if debug_programmerhelper == 1:
                cv_logger.info("Send AES cancellation ccert using Programmer flow with helper - %s"%(qek_file))
                return_code = run_command("quartus_pgm -c %d -m jtag -o \"ip;%s\"") %(self.dut.dut_cable, ccert_file)
            else:
                cv_logger.info("Send AES cancellation ccert using Programmer flow - %s"%(qek_file))
                return_code = run_command("quartus_pgm -c %d -m jtag -o \"p;%s\"" % (self.dut.dut_cable, ccert_file))    

        if (re.search("Error", str(return_code)) == None):
            local_respond = [0]
        else :
            local_respond = [1]

        if (not success) and local_respond != [0]:
            cv_logger.info("Failed to program AES cancellation ccert as EXPECTED with respond: %s" %local_respond)
        elif success and local_respond != [0]:
            print_err("ERROR :: Failed to program AES cancellation ccert with respond: %s" %local_respond)

        return local_respond

    '''
    Modify   : Send device permit kill certificate
    Input    : ccert_file - kill certificate file in .ccert format
               test_program -- True for virtual write, False otherwise
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
    Output   : response -- the respond packet of the sdm command
    '''
    def send_kill_ccert(self, ccert_file, test_program=True,success=True, exp_err=0):
        cv_logger.info("Sending Device Permit Kill CCERT")
        security_datatype = SecurityDataTypes('ANTI TAMPER')

        # syscon will see ccert data loss in emulator
        if os.environ.get('FWVAL_PLATFORM') == "emulator" :

            try :
                # force syscon to release platform
                if self.dut.system_console != None :
                    self.dut.close_platform()
            except :
                pass

            try :
                return_msg = ""
                qpgm_cmd = "quartus_pgm -c%d -mJTAG -o\"p;%s\"" % (self.dut.dut_cable, ccert_file)
                return_msg = run_command(qpgm_cmd, timeout=120)
            except :
                if not success :
                    cv_logger.info("Failed to program cancellation fuses as EXPECTED with respond: %s" %local_respond)
                else :
                    print_err("ERROR :: Failed to program cancellation fuses UNEXPECTEDLY with respond: %s" %local_respond)
            if re.search("Error", return_msg) == None:
                local_respond = [0,0]

            if self.dut.system_console == None :
                self.dut.open_platform()

        else :
            cert_content = security_datatype.read_ccert(ccert_file)

            if not (self._fuse_write_disabled and test_program):
                cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
                test_program = True

            local_respond = self.jtag_send_certificate(cert_data=cert_content,
                                                       test_program=test_program,
                                                       success=success)

            if (not success) and local_respond[1] != 0:
                cv_logger.info("Failed to program kill fuses as EXPECTED with respond: %s" %local_respond)
                if exp_err:
                    assert_err(local_respond[1] == exp_err,
                        "ERROR :: ERROR value mismatched Measured = 0x%x and Expected = 0x%x" %(local_respons[1],exp_err))

            elif success and local_respond[1] != 0:
                print_err("ERROR :: Failed to program kill fuses UNEXPECTEDLY with respond: %s" %local_respond)

        return local_respond[1]


    '''
    Modify   : Send Beta Loader certificate
    Input    : ccert_file - Beta Loader CCERT file in .ccert format
               test_program -- True for virtual write, False otherwise
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
               exp_err -- default 0, checks expected error if stated
    Output   : response -- the respond packet of the sdm command
    '''
    def send_beta_loader_ccert(self, ccert_file, test_program=True,success=True):
        cv_logger.info("Sending Beta Loader CCERT")
        security_datatype = SecurityDataTypes('BETA LOADER')
        cert_content = security_datatype.read_ccert(ccert_file)

        if not (self._fuse_write_disabled and test_program):
            cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
            test_program = True

        local_respond = self.jtag_send_certificate(cert_data=cert_content,
                                                   test_program=test_program, success=success)

        return local_respond


    '''
    Modify   : Send user AES certificate
    Input    : ccert_file - AES CCERT file in .ccert format
               test_program -- True for virtual write, False otherwise
               success -- Checks if the command is successful or not, True if the command should response with no error code, False if command should respond with error code
               exp_err -- default 0, checks expected error if stated
    Output   : response -- the respond packet of the sdm command
    '''
    def send_user_aeskey_ccert(self, ccert_file, test_program=True,success=True):
        cv_logger.info("Sending user AES CCERT")
        security_datatype = SecurityDataTypes('AES KEY')

        # syscon will see ccert data loss in emulator
        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            try :
                return_msg = ""
                qpgm_cmd = "quartus_pgm -c%d -mJTAG -o\"p;%s\"" % (self.dut.dut_cable, ccert_file)
                return_msg = run_command(qpgm_cmd, timeout=120)
            except :
                if not success :
                    cv_logger.info("Failed to program cancellation fuses as EXPECTED with respond: %s" %local_respond)
                else :
                    print_err("ERROR :: Failed to program cancellation fuses UNEXPECTEDLY with respond: %s" %local_respond)

            if re.search("Error", return_msg) == None:
                local_respond = [0,0]

        else :
            cert_content = security_datatype.read_ccert(ccert_file)

            cv_logger.info("Sending user AES key ccert")

            if not (self._fuse_write_disabled and test_program):
                cv_logger.debug("Forcing the Test Program to set as True to Protect the device ........................")
                test_program = True

            local_respond = self.jtag_send_certificate(cert_data=cert_content,
                    test_program=test_program, success=success)

        return local_respond

    '''
    Modify  : self, program_aeskey allows user to program the user AES key to storage device selected using programmer tool (with/without helper image) or SDM command via JTAG
    Input   : qek -- input qek file
              pem_file -- input user pem file
              qky_file -- input qky file with permission=64
              ccert_file -- input user aes key ccert file
              passphrase_file -- password storage file
              option -- 'sdm' = send SDM command via JTAG, 'programmer' = use quartus_pgm tool to program aes key
              key_storage -- encryption key storage selection
              debug_programmerhelper -- True for using programmer tool with helper image, False otherwise
              test_program -- True for virtual write, False otherwise
              type_of_key -- key source user or intel own
              key_wrap -- default 0, use class AES_CCERT_VARIANT
              success -- checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code.
              reserve -- values to put onto the reserve bits, must be within [0, 8388607] <- now there are 23 bits of reserve bits (b30:8). this could change in the future.
              ccert_device  -- require to input to generate correct sdm ccert format
              test_mode -- input 'on' to use test mode flow
              non_volatile -- input to use physical flow and make changes to fuse
              cancel_id -- cancel id of the AES ccert
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def program_aeskey(self, qek, passphrase_file, pem_file=None, qky_file=None, option='sdm',
        key_storage='BBRAM', success=True, debug_programmerhelper=False, test_program=1, reserve=0,
        type_of_key='user_key', ccert_file=None, key_wrap=None, iv=None, ccert_device=None, test_mode=None, non_volatile=None, cancel_id=None):

        # Lets start with fail condition in case anything goes wrong
        # if things is successful the value will local_respond will be ovewrite as = [0]
        local_respond = 0

        # Use AES root key certificate to program the aes key if quartus version > 21.0
        acds_version = os.environ['QUARTUS_VERSION']

        if ((compare_quartus_version(acds_version, '21.1') == 0) or (compare_quartus_version(acds_version, '21.1') == 1)):

            if ccert_file == None:

                if (qky_file==None) or (pem_file==None):
                    assert_err(0, "ERROR :: Please input qky_file and pem_file keys with SIGN_OWNER_AES permission to enable ccert method from 21.1 onwards")

                if key_wrap == None:
                    #Use BBRAM internal wrap from 21.2 onwards
                    if (key_storage == "BBRAM" and (compare_quartus_version(acds_version, '21.2') == -1)):
                        key_wrap = 'NO_WRAP'
                    elif (key_storage == "EFUSE" or key_storage == "BBRAM"):
                        key_wrap = 'INTERNAL'
                    elif (key_storage == "OFF_CHIP"):
                        key_wrap = 'INTERNAL'
                    else:
                        assert_err(0, "ERROR :: key_storage type does not match the key_wrap selection")

                qek_filename = os.path.basename(qek)
                qek_filename = os.path.splitext(qek_filename)[0]
                ccert_file = "signed_user_aeskey_" + key_storage + "_" + qek_filename + ".ccert"

                # Generate signed user AES Root Key Certificate
                gen_user_aeskey_ccert(output_ccert_file=ccert_file, key_storage=key_storage, key_wrap=key_wrap,
                    qek_file=qek, password=passphrase_file, pem_file=pem_file, qky_file=qky_file, iv=iv, ccert_device=ccert_device, test_mode=test_mode, non_volatile=non_volatile, cancel_id=cancel_id)

        if option == 'sdm':
            cv_logger.info("Program AES key to %s by sending SDM command thru JTAG - %s"%(key_storage, qek))

            if (compare_quartus_version(acds_version, '21.1') == -1):
                # Program AES key
                local_respond = self.qek_program_mbx(key_storage=key_storage, aes_password=passphrase_file, aes_key_qek=qek, success=success,test_program=test_program, type_of_key=type_of_key, reserve=reserve)
            else:
                local_respond = self.send_user_aeskey_ccert(ccert_file, test_program=test_program, success=success)

        elif option == 'programmer':

            if key_storage == "EFUSE":
                key_storage = "Virtual eFuses"

            if key_storage == "Real eFuses":
                assert_err(0, "ERROR :: You are calling %s! Failing test to prevent permanently altering the device" %key_storage)

            if debug_programmerhelper == 1:
                cv_logger.info("Program AES key to %s using Programmer flow with helper - %s"%(key_storage, qek))
                if (compare_quartus_version(acds_version,'21.1') == -1):
                    return_code = run_command_fail_handling("quartus_pgm -c %d -m jtag --key_storage=\"%s\" --password=%s -o \"ip;%s\"" % (self.dut.dut_cable, key_storage, passphrase_file, qek), success=success, skip=0)
                else:
                    return_code = run_command_fail_handling("quartus_pgm -c %d -m jtag -o \"ip;%s\"" %(self.dut.dut_cable, ccert_file), success=success, skip=0)
            else:
                cv_logger.info("Program AES key to %s using Programmer flow - %s"%(key_storage, qek))
                if (compare_quartus_version(acds_version,'21.1') == -1):
                    return_code = run_command_fail_handling("quartus_pgm -c %d -m jtag --key_storage=\"%s\" --password=%s -o \"p;%s\"" % (self.dut.dut_cable, key_storage, passphrase_file, qek), success=success, skip=0)
                else:
                    return_code = run_command_fail_handling("quartus_pgm -c %d -m jtag -o \"p;%s\"" % (self.dut.dut_cable, ccert_file), success=success, skip=0)

            if re.search("Error", str(return_code)) == None:
                local_respond = [0]

            if (not success) and local_respond != [0]:
                cv_logger.info("Failed to program AES key as EXPECTED with respond: %s" %local_respond)
            elif success and local_respond != [0]:
                print_err("ERROR :: Failed to program AES key UNEXPECTEDLY with respond: %s" %local_respond)

        return local_respond

    '''
    Requires : fw must be loaded onto device
    Modifies : sends efuse_read command to read UID from device
    Output  : hex string of device UID, with leading zeros filled up to 16 hex digits, without "0x" in front
    '''
    def get_uid_efuse(self):
        READ_BANK = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['unique_id_long_1'][0]
        READ_ROW  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY]['unique_id_long_1'][1]

        cv_logger.info("Get UID by reading bank 0 row 13-14")
        respond = self.efuse_read(bank=READ_BANK, row=READ_ROW, num_row=2)
        uid_int = respond[0] | respond[1] << 32
        uid_16_hex = hex(uid_int)[2:].zfill(16)

        cv_logger.info("UID is %s" %uid_16_hex)
        return uid_16_hex

    '''
    Requires : fw must be loaded onto device
    Modifies : sends GET_DEVICE_IDENTITY command to get HMAC from device
    Output  : hex string of device HMAC, with leading zeros filled up to 64 hex digits, without "0x" in front
    '''
    def get_hmac(self):
        cv_logger.info("Get HMAC by sending GET_DEVICE_IDENTITY command")
        respond = self.jtag_send_sdmcmd(SDM_CMD['GET_DEVICE_IDENTITY'])

        hmac_int = respond[1] | respond[2] << 32 | respond[3] << 2*32 | respond[4] << 3*32 | respond[5] << 4*32 | respond[6] << 5*32 | respond[7] << 6*32 | respond[8] << 7*32
        hmac_64_hex = hex(hmac_int)
        if hmac_64_hex[-1] == "L":
            hmac_64_hex = hmac_64_hex[2:-1].zfill(64)   #remove "0x" prefix, and get rid of the "L" that indicates long data type
        else:
            hmac_64_hex = hmac_64_hex[2:].zfill(64)     #if no L, then just remove "0x" prefix

        cv_logger.info("HMAC is %s" %hmac_64_hex)
        return hmac_64_hex

    '''
    To determine if the loaded firmware has debug enabled
    Require : firmware must be loaded
    Modify  : self, sends get_service_paths processor via system console
    Output  : True or False
    Note    : for debug disabled firmware, we should only get paths for CRETE CJTAG Controller
              debug enabled firmware would return many more different processor path
    '''
    def is_debug_en(self):
        cv_logger.info("Checking if debug enabled by looking at processor paths...")
        cv_logger.info("Debug disabled should only have CRETE CJTAG Controller paths")
        resp = self.dut.send_system_console("get_service_paths processor", print_console=3)

        for path in resp:
            if re.search(r".*CRETE \d+ CJTAG Controller", path) == None:
                cv_logger.info("Debug is enabled!")
                return True

        cv_logger.info("Debug is disabled!")
        return False

    '''
    Input   : bitstream_ba: byte array of the bitstream
    Output  : size of the firmware section for given bitstream
    '''
    def get_firmware_size(self, bitstream_ba):
        firmware_size_start = CMF_DESCRIPTOR['fw_sec_size'][0]
        firmware_size_end   = firmware_size_start + CMF_DESCRIPTOR['fw_sec_size'][1]
        src_buff = bitstream_ba[firmware_size_start:firmware_size_end]
        src_buff_le = reverse_arr(src_buff)
        return int(binascii.hexlify(src_buff_le),16)

    '''
    Input   : en -- enables the check for the specific pins (1 enable, 0 disable)
              ast -- if 1, throws assertion when pin mismatch. if 0, no assertion just output
              log_error -- enable to log the error into reg.rout
    Optional: en=1, disable as required
              ast=0, enable as required
    Output  : True if correct, False if incorrect
    Comment : We may have to disable certain check if board does not support the pin
              For checking if pin is supported in platform specific, that should be in
              another library specific for said platform
    Example : self.verify_pin(init_done_en=0)
    Note    : do not set avst_ready_en=1 unless you are using AvstTest
    '''
    def verify_pin(self, nstatus_en=1, init_done_en=0, config_done_en=1, avst_ready_en=0, ast=0, log_error=1, wait_time_out_check=False, index=""):
        cv_logger.info("V%d :: Verify Pin" %(self._verify_counter))
        self._verify_counter = self._verify_counter + 1
        local_pass = True
        err_msgs = []
        index = str(index)
        cv_logger.info("index number for arc-resource-page = %s" %index)

        #if user disabled the gpio, disabled that pin check
        if self._CONFIG_DONE == None or self.DUT_FAMILY == "diamondmesa":
            cv_logger.warning("User disabled the CONFIG_DONE gpio connector, skipping check for this pin.")
            config_done_en = 0
        if self._INIT_DONE == None:
            cv_logger.warning("User disabled the INIT_DONE gpio connector, skipping check for this pin")
            init_done_en = 0

        #if SDMIO_0 is used by VID, disable that pin check
        if ( ("DUT%s_VID_SCL" %index) in os.environ):
            if ( os.environ[('DUT%s_VID_SCL' %index)] == "SDMIO0" ) :
                cv_logger.info("Board Info [DUT%s_VID_SCL] is SDMIO0 pin" %index)
                if(self._INIT_DONE == "sdmio_0"):
                    cv_logger.warning("Disable check for INIT_DONE pin at SDMIO_0, it is used for [DUT%s_VID_SCL]" %index)
                    init_done_en = 0
                elif(self._CONFIG_DONE == "sdmio_0"):
                    cv_logger.warning("Disable check for CONFIG_DONE pin at SDMIO_0, it is used for [DUT%s_VID_SCL]" %index)
                    config_done_en = 0

        #check the enabled pins
        if(nstatus_en):
            nstatus_output  = self.nstatus.get_output()
            if((wait_time_out_check)):
                counter = 0
                while((nstatus_output != self.exp_pin['NSTATUS']) and (counter <= self.DUT_FILTER.time_out_pin)):
                    nstatus_output  = self.nstatus.get_output()
                    fwval.delay(5)
                    counter = counter + 5
                if(counter <= self.DUT_FILTER.time_out_pin):
                    cv_logger.info("Time took for  nSTATUS=%d  is = %dms" %(self.exp_pin['NSTATUS'],counter))
                else:
                    cv_logger.debug("Time out waiting for nSTATUS=%d after %dms" %(self.exp_pin['NSTATUS'],counter))

            cv_logger.info("NSTATUS = %d" % nstatus_output)
            if nstatus_output != self.exp_pin['NSTATUS']:
                local_pass = False
                err_msgs.append("ERROR :: Expected NSTATUS: %d, Measured NSTATUS: %d" %(self.exp_pin['NSTATUS'], nstatus_output))
            else :
                cv_logger.info("Measured NSTATUS: %d matched expectation" % nstatus_output)

        if(init_done_en):
            init_done_output  = self.init_done.get_output()
            if((wait_time_out_check)):
                counter = 0
                while((init_done_output != self.exp_pin['INIT_DONE']) and (counter <= self.DUT_FILTER.time_out_pin)):
                    init_done_output  = self.init_done.get_output()
                    fwval.delay(5)
                    counter = counter + 5
                if(counter <= self.DUT_FILTER.time_out_pin):
                    cv_logger.info("Time took for  INIT_DONE=%d  is = %dms" %(self.exp_pin['INIT_DONE'],counter))
                else:
                    cv_logger.debug("Time out waiting for INIT_DON=%d  after %dms" %(self.exp_pin['INIT_DONE'],counter))

            cv_logger.info("INIT_DONE = %d" % init_done_output)
            if init_done_output != self.exp_pin['INIT_DONE']:
                local_pass = False
                err_msgs.append("ERROR :: Expected INIT_DONE: %d, Measured INIT_DONE: %d" %(self.exp_pin['INIT_DONE'], init_done_output))
            else :
                cv_logger.info("Measured INIT_DONE: %d matched expectation" % init_done_output)
        if(config_done_en):
            config_done_output  = self.config_done.get_output()
            if((wait_time_out_check)):
                counter = 0
                while((config_done_output != self.exp_pin['CONFIG_DONE']) and (counter <= self.DUT_FILTER.time_out_pin)):
                    config_done_output  = self.config_done.get_output()
                    fwval.delay(5)
                    counter = counter + 5
                if(counter <= self.DUT_FILTER.time_out_pin):
                    cv_logger.info("Time took for  CONFIG_DONE=%d is = %dms" %(self.exp_pin['CONFIG_DONE'],counter))
                else:
                    cv_logger.debug("Time out waiting for CONFIG_DONE=%d  after %dms" %(self.exp_pin['CONFIG_DONE'],counter))

            cv_logger.info("CONFIG_DONE = %d" % config_done_output)
            if config_done_output != self.exp_pin['CONFIG_DONE']:
                local_pass = False
                err_msgs.append("ERROR :: Expected CONFIG_DONE: %d, Measured CONFIG_DONE: %d" %(self.exp_pin['CONFIG_DONE'], config_done_output))
            else :
                cv_logger.info("Measured CONFIG_DONE: %d matched expectation" % config_done_output)
        if(avst_ready_en):
            avst_ready_output  = self.avst_ready.get_output()
            if((wait_time_out_check)):
                counter = 0
                while((avst_ready_output != self.exp_pin['AVST_READY']) and (counter <= self.DUT_FILTER.time_out_pin)):
                    avst_ready_output  = self.avst_ready.get_output()
                    fwval.delay(5)
                    counter = counter + 5
                if(counter <= self.DUT_FILTER.time_out_pin):
                    cv_logger.info("Time took for  AVST_READY=%d is = %dms" %(self.exp_pin['AVST_READY'],counter))
                else:
                    cv_logger.debug("Time out waiting for AVST_READY =%d after %dms" %(self.exp_pin['AVST_READY'],counter))

            cv_logger.info("AVST_READY = %d" % avst_ready_output)
            if avst_ready_output != self.exp_pin['AVST_READY']:
                local_pass = False
                err_msgs.append("ERROR :: Expected AVST_READY: %d, Measured AVST_READY: %d" %(self.exp_pin['AVST_READY'], avst_ready_output))
            else :
                cv_logger.info("Measured AVST_READY: %d matched expectation" % avst_ready_output)

        #print the pins with unexpected values
        if err_msgs:
            for err in err_msgs:
                if(log_error):
                    print_err(err)
            if ast:
                assert_err(0, "ERROR :: Pin incorrect")
            else:
                if(log_error):
                    print_err("ERROR :: Pin incorrect")
        else:
            cv_logger.info("Pin result same as expectation")
        return local_pass

    def get_raw_prov_data(self) :
        '''
        Input   : None
        Require : only call this after entered CMF state
        Output  : print and return raw data from GET_PROV_DATA
        Example ::
            * get a list of GET_PROV_DATA response
                test.get_raw_prov_data()
        '''
        local_respond = self.jtag_send_sdmcmd(SDM_CMD['GET_PROV_DATA'])
        cv_logger.info(local_respond)
        return local_respond

    def verify_prov_status(self, ast=0) :
        '''
        Input   : None
        Require : only call this after entered CMF state. use "verify" only after update_prov_data()
        Output  : True for pass, False for fail
        Example ::
            * print all and check all prov data
                test.verify_prov_status()
            * print all and check all prov data, assert if mismatch found
                test.verify_prov_status(ast=1)
        '''
        return self.get_prov_data(key="verify", ast=ast)

    def get_prov_data(self, key=None, ast=0) :
        '''
        Input   : key -- keyword to retrieve value from provision data. "None" to print all. "verify" to print and check
        Require : only call this after entered CMF state. use "verify" only after update_prov_data()
        Output  : True if correct, False if incorrect
                  if key is provided, return the value
        Example ::
            * print all prov data
                test.get_prov_data()
            * get specific value
                cosign = test.get_prov_data(key="COSIGN_STATUS")
            * print and verify all prov data. Call test.update_prov_data() first if necessary. use verify_prov_data() for shorthand
                test.get_prov_data(key="verify")
            * print and verify all prov data and assert if mismatch found. Call test.update_prov_data() first if necessary. use verify_prov_data() for shorthand
                test.get_prov_data(key="verify", ast=1)
        '''

        default_value = 0xFEABD

        # dict to hold prov data
        prov_status = {
                        'SKIP_PROV_CMD'                              : default_value,
                        'PROV_STATUS_CODE'                           : default_value,
                        'INTEL_CANC_STATUS'                          : default_value,
                        'COSIGN_STATUS'                              : default_value,
                        'OWNER_RH0_CANC_STATUS'                      : default_value,
                        'OWNER_RH1_CANC_STATUS'                      : default_value,
                        'OWNER_RH2_CANC_STATUS'                      : default_value,
                        'OWNER_RH3_CANC_STATUS'                      : default_value,
                        'OWNER_RH4_CANC_STATUS'                      : default_value,
                        'HASH_COUNT'                                 : default_value,
                        'HASH_TYPE'                                  : default_value,
                        'HASH_SLOT_VALID_STATUS'                     : default_value,
                        'OWNER_RH0'                                  : default_value,
                        'OWNER0_EXPKEY_CANC_STATUS'                  : default_value,
                        'OWNER_RH1'                                  : default_value,
                        'OWNER1_EXPKEY_CANC_STATUS'                  : default_value,
                        'OWNER_RH2'                                  : default_value,
                        'OWNER2_EXPKEY_CANC_STATUS'                  : default_value,
                        'OWNER_RH3'                                  : default_value,
                        'OWNER3_EXPKEY_CANC_STATUS'                  : default_value,
                        'OWNER_RH4'                                  : default_value,
                        'OWNER4_EXPKEY_CANC_STATUS'                  : default_value,
                        'BIG_COUNTER_BASE'                           : default_value,
                        'BIG_COUNTER'                                : default_value,
                        'SVN3'                                       : default_value,
                        'SVN2'                                       : default_value,
                        'SVN1'                                       : default_value,
                        'SVN0'                                       : default_value,
                        'KEY_SLOT_B31_24'                            : default_value,
                        'KEY_SLOT_B23_20'                            : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS5'                 : default_value,
                        'KEY_SLOT_B19_16'                            : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS4'                 : default_value,
                        'KEY_SLOT_B15_12'                            : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS3'                 : default_value,
                        'KEY_SLOT_B11_08_OCSKEY_1'                   : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS2'                 : default_value,
                        'KEY_SLOT_B07_04_OCSKEY_0'                   : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS1'                 : default_value,
                        'KEY_SLOT_B03_00_UAESKEY_0'                  : default_value,
                        'eFUSE_IFP_KEY_SLOT_STATUS0'                 : default_value,
                        'KEY_SLOT_STATUS_B31_24'                     : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS5'                 : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS4'                 : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS3'                 : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS2'                 : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS1'                 : default_value,
                        'FLASH_IFP_KEY_SLOT_STATUS0'                 : default_value,
                        'FPM_CTR_VALUE'                              : default_value,
                        'OWNERSHIP_TRANSFER_MODE_STATUS'             : default_value,
                        'NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES' : default_value,
        }

        if key is not None and key != "verify" :
            assert_err(key in prov_status, "Invalid key")
            
        if self._scoreboard_state['intel_canc_exp_update_done'] == 0 :
            # get physical efuse value for Intel keyid cancellation status once
            # to compare with prov_data
            key_var = 'psg_public_key_cancellation'
            bank = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][0]
            row  = efuse_dict.EFUSES_LOCATION[self.DUT_FAMILY][key_var][1]
            intel_status_list = self.efuse_read(bank=bank, row=row, num_row=4, success=True)
            intel_status = intel_status_list[0]
            i = 0
            for val in intel_status_list :
                if bin(val).count("1") != bin(intel_status).count("1") :
                    print_err("ERROR :: Unexpected Intel cancellation value %d from bank %d row %d" % (val, bank, row+i))
                i += 1
            self.update_prov_exp(intel_status=intel_status)
            self._scoreboard_state['intel_canc_exp_update_done'] = 1

        err_msgs = []
        local_pass = True

        local_respond = self.get_raw_prov_data()
        local_respond_length = len(local_respond)
        local_header = int(local_respond[0])



        if local_header == 1 :
            print_err("ERROR :: Unrecognized get_prov_data command. Is device still in bootrom?")
            local_pass = False
        local_number_element = local_header / 4096
        if (local_respond_length-1) != local_number_element :
            print_err("ERROR :: Expected device in CMF stage.\nExpected Length as per header = %d, but received length = %d" %(local_number_element, (local_respond_length-1)))
            local_pass = False

        #Extract the values and fill the local dictionary
        local_counter = 0

        for element in local_respond :
            if local_counter == 1 :
                prov_status['SKIP_PROV_CMD'] = int(getbitvalue(element,31))
                prov_status['PROV_STATUS_CODE'] = int(getbitvalue(element,30,0))

            elif local_counter == 2 :
                prov_status['INTEL_CANC_STATUS'] = int(element)

            elif local_counter == 3 :
                prov_status['COSIGN_STATUS'] = int(getbitvalue(element,19))
                prov_status['OWNER_RH0_CANC_STATUS'] = int(getbitvalue(element,16))
                prov_status['OWNER_RH1_CANC_STATUS'] = int(getbitvalue(element,17))
                prov_status['OWNER_RH2_CANC_STATUS'] = int(getbitvalue(element,18))
                prov_status['OWNER_RH3_CANC_STATUS'] = int(getbitvalue(element,20))
                prov_status['OWNER_RH4_CANC_STATUS'] = int(getbitvalue(element,21))
                prov_status['HASH_COUNT'] = int(getbitvalue(element,15,8))
                prov_status['HASH_TYPE'] = int(getbitvalue(element,7,0))
                prov_status['HASH_SLOT_VALID_STATUS'] = int(getbitvalue(element,31,25))

            # Handling for SDM1.5
            # In SDM1.5, there are 3 rows for key slot 
            sdm_version = os.getenv('DUT_SDM_VERSION')
            if (sdm_version == "1.5"):
            
                if local_counter == (local_respond_length-6) :
                        prov_status['BIG_COUNTER_BASE'] = int(getbitvalue(element,31,24))
                        prov_status['BIG_COUNTER'] = int(getbitvalue(element,23,0))

                elif local_counter == (local_respond_length-5) :
                    prov_status['SVN3'] = int(getbitvalue(element,31,24))
                    prov_status['SVN2'] = int(getbitvalue(element,23,16))
                    prov_status['SVN1'] = int(getbitvalue(element,15,8))
                    prov_status['SVN0'] = int(getbitvalue(element,7,0))
                    
                elif local_counter == (local_respond_length-4) :
                    prov_status['KEY_SLOT_B31_24'] = int(getbitvalue(element,31,24))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS5'] = int(getbitvalue(element,23,20))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS4'] = int(getbitvalue(element,19,16))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS3'] = int(getbitvalue(element,15,12))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS2'] = int(getbitvalue(element,11,8))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS1'] = int(getbitvalue(element,7,4))
                    prov_status['eFUSE_IFP_KEY_SLOT_STATUS0'] = int(getbitvalue(element,3,0))
                    
                elif local_counter == (local_respond_length-3) :
                    prov_status['KEY_SLOT_STATUS_B31_24'] = int(getbitvalue(element,31,24))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS5'] = int(getbitvalue(element,23,20))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS4'] = int(getbitvalue(element,19,16))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS3'] = int(getbitvalue(element,15,12))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS2'] = int(getbitvalue(element,11,8))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS1'] = int(getbitvalue(element,7,4))
                    prov_status['FLASH_IFP_KEY_SLOT_STATUS0'] = int(getbitvalue(element,3,0))
                    
                elif local_counter == (local_respond_length-2) :
                    prov_status['FPM_CTR_VALUE'] = int(getbitvalue(element,7,0))

                elif local_counter == (local_respond_length-1) :
                    prov_status['OWNERSHIP_TRANSFER_MODE_STATUS'] = int(getbitvalue(element,11,8))
                    prov_status['NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES'] = int(getbitvalue(element,3,0))
            
            else:
            
                if local_counter == (local_respond_length-3) :
                        prov_status['BIG_COUNTER_BASE'] = int(getbitvalue(element,31,24))
                        prov_status['BIG_COUNTER'] = int(getbitvalue(element,23,0))

                elif local_counter == (local_respond_length-2) :
                    prov_status['SVN3'] = int(getbitvalue(element,31,24))
                    prov_status['SVN2'] = int(getbitvalue(element,23,16))
                    prov_status['SVN1'] = int(getbitvalue(element,15,8))
                    prov_status['SVN0'] = int(getbitvalue(element,7,0))
                    
                elif local_counter == (local_respond_length-1) :
                    prov_status['KEY_SLOT_B31_24'] = int(getbitvalue(element,31,24))
                    prov_status['KEY_SLOT_B23_20'] = int(getbitvalue(element,23,20))
                    prov_status['KEY_SLOT_B19_16'] = int(getbitvalue(element,19,16))
                    prov_status['KEY_SLOT_B15_12'] = int(getbitvalue(element,15,12))
                    prov_status['KEY_SLOT_B11_08_OCSKEY_1'] = int(getbitvalue(element,11,8))
                    prov_status['KEY_SLOT_B07_04_OCSKEY_0'] = int(getbitvalue(element,7,4))
                    prov_status['KEY_SLOT_B03_00_UAESKEY_0'] = int(getbitvalue(element,3,0))

            local_counter += 1

        # secp384r1
        if prov_status['HASH_TYPE'] == 2 :
            hash_size = 12
        elif prov_status['HASH_TYPE'] == 1 :
            # not longer supported on fm6revb onwards
            hash_size = 8
        else :
            err_msgs.append("ERROR :: HASH_TYPE is unrecognized. Measured = %d" % (prov_status['HASH_TYPE']))
            hash_size = 12
            local_pass = False

        hash_start_position = 4
        hash_end_position = 4 + hash_size
        hash_canc_status = hash_end_position
        for slot in range(prov_status['HASH_COUNT']+1) :
            _owner_rh = "OWNER_RH%s" % (slot)
            _owner_expkey_canc_status = "OWNER%s_EXPKEY_CANC_STATUS" % (slot)
            prov_status[_owner_rh] = local_respond[hash_start_position:hash_end_position]
            prov_status[_owner_expkey_canc_status] = local_respond[hash_canc_status]
            hash_start_position = hash_canc_status + 1
            hash_end_position = hash_start_position + hash_size
            hash_canc_status = hash_end_position

        if prov_status['HASH_COUNT'] > self.RH_SLOT_COUNT-1 :
            err_msgs.append("ERROR :: HASH_COUNT is invalid. Measured = %d when the max is %d" % (prov_status['HASH_COUNT'], self.RH_SLOT_COUNT))
            local_pass = False


        if key is None or key == "verify" :
            cv_logger.info("provision_data['SKIP_PROV_CMD']                  = 0x%x" %(prov_status['SKIP_PROV_CMD']))
            cv_logger.info("provision_data['PROV_STATUS_CODE']               = 0x%x" %(prov_status['PROV_STATUS_CODE']))
            cv_logger.info("provision_data['INTEL_CANC_STATUS']              = 0x%x" %(prov_status['INTEL_CANC_STATUS']))
            cv_logger.info("provision_data['COSIGN_STATUS']                  = 0x%x" %(prov_status['COSIGN_STATUS']))

            for slot in range(self.RH_SLOT_COUNT) :
                _owner_rh_canc_status = "OWNER_RH%s_CANC_STATUS" % (slot)
                cv_logger.info("provision_data['%s']          = 0x%x" %(_owner_rh_canc_status, prov_status[_owner_rh_canc_status]))
            cv_logger.info("provision_data['HASH_COUNT']                     = 0x%x" %(prov_status['HASH_COUNT']))
            cv_logger.info("provision_data['HASH_TYPE']                      = 0x%x" %(prov_status['HASH_TYPE']))
            cv_logger.info("provision_data['HASH_SLOT_VALID_STATUS']         = 0x%x" %(prov_status['HASH_SLOT_VALID_STATUS']))

            for slot in range(prov_status['HASH_COUNT']+1) :
                _owner_rh = "OWNER_RH%s" % (slot)
                _owner_expkey_canc_status = "OWNER%s_EXPKEY_CANC_STATUS" % (slot)
                cv_logger.info("provision_data['{}']                      = {}".format(_owner_rh, ', '.join(hex(x) for x in prov_status[_owner_rh])))
                cv_logger.info("provision_data['%s']      = 0x%x" %(_owner_expkey_canc_status, prov_status[_owner_expkey_canc_status]))
            cv_logger.info("provision_data['BIG_COUNTER_BASE']               = 0x%x" %(prov_status['BIG_COUNTER_BASE']))
            cv_logger.info("provision_data['BIG_COUNTER']                    = 0x%x" %(prov_status['BIG_COUNTER']))
            cv_logger.info("provision_data['SVN3']                           = 0x%x" %(prov_status['SVN3']))
            cv_logger.info("provision_data['SVN2']                           = 0x%x" %(prov_status['SVN2']))
            cv_logger.info("provision_data['SVN1']                           = 0x%x" %(prov_status['SVN1']))
            cv_logger.info("provision_data['SVN0']                           = 0x%x" %(prov_status['SVN0']))
            
            if (sdm_version == "1.5"):
                cv_logger.info("provision_data['KEY_SLOT_B31_24']                = 0x%x" %(prov_status['KEY_SLOT_B31_24']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS5']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS5']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS4']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS4']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS3']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS3']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS2']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS2']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS1']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS1']))
                cv_logger.info("provision_data['eFUSE_IFP_KEY_SLOT_STATUS0']            = 0x%x" %(prov_status['eFUSE_IFP_KEY_SLOT_STATUS0']))
                cv_logger.info("provision_data['KEY_SLOT_STATUS_B31_24']         = 0x%x" %(prov_status['KEY_SLOT_STATUS_B31_24']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS5']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS5']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS4']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS4']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS3']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS3']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS2']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS2']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS1']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS1']))
                cv_logger.info("provision_data['FLASH_IFP_KEY_SLOT_STATUS0']     = 0x%x" %(prov_status['FLASH_IFP_KEY_SLOT_STATUS0']))       
                cv_logger.info("provision_data['FPM_CTR_VALUE']                  = 0x%x" %(prov_status['FPM_CTR_VALUE'])) 
                cv_logger.info("provision_data['OWNERSHIP_TRANSFER_MODE_STATUS'] = 0x%x" %(prov_status['OWNERSHIP_TRANSFER_MODE_STATUS']))
                cv_logger.info("provision_data['NUM_OWNSHIP_TRSF_OPPORTUNITIES'] = 0x%x" %(prov_status['NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES']))
            else:
                cv_logger.info("provision_data['KEY_SLOT_B31_24']                = 0x%x" %(prov_status['KEY_SLOT_B31_24']))
                cv_logger.info("provision_data['KEY_SLOT_B23_20']                = 0x%x" %(prov_status['KEY_SLOT_B23_20']))
                cv_logger.info("provision_data['KEY_SLOT_B19_16']                = 0x%x" %(prov_status['KEY_SLOT_B19_16']))
                cv_logger.info("provision_data['KEY_SLOT_B15_12']                = 0x%x" %(prov_status['KEY_SLOT_B15_12']))
                cv_logger.info("provision_data['KEY_SLOT_B11_08_OCSKEY_1']       = 0x%x" %(prov_status['KEY_SLOT_B11_08_OCSKEY_1']))
                cv_logger.info("provision_data['KEY_SLOT_B07_04_OCSKEY_0']       = 0x%x" %(prov_status['KEY_SLOT_B07_04_OCSKEY_0']))
                cv_logger.info("provision_data['KEY_SLOT_B03_00_UAESKEY_0']      = 0x%x" %(prov_status['KEY_SLOT_B03_00_UAESKEY_0']))

            if key == "verify" :

                cv_logger.info("Comparing prov_status with expectation...")

                # get list of key
                prov_status_keys = list(prov_status.keys())
                # exclude keys that will be checked separately
                for s in range(5) :
                    try:
                        prov_status_keys.remove("OWNER_RH%s_CANC_STATUS" % (s))
                        prov_status_keys.remove("OWNER%s_EXPKEY_CANC_STATUS" % (s))
                        prov_status_keys.remove("OWNER_RH%s" % (s))
                    except: pass

                prov_status_keys.remove("HASH_SLOT_VALID_STATUS")                

                if (sdm_version != "1.5"):
                
                    prov_status_keys.remove("KEY_SLOT_B31_24")
                    prov_status_keys.remove("KEY_SLOT_STATUS_B31_24")
                    prov_status_keys.remove("FPM_CTR_VALUE")
                    prov_status_keys.remove("OWNERSHIP_TRANSFER_MODE_STATUS")
                    prov_status_keys.remove("NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES")
                    del self.exp_prov_status["KEY_SLOT_B31_24"]
                    del self.exp_prov_status["KEY_SLOT_STATUS_B31_24"]
                    del self.exp_prov_status["FPM_CTR_VALUE"]
                    del self.exp_prov_status["OWNERSHIP_TRANSFER_MODE_STATUS"]
                    del self.exp_prov_status["NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES"]
                    
                    for s in range(6) :
                        try:
                            prov_status_keys.remove("eFUSE_IFP_KEY_SLOT_STATUS%s" % (s))
                            prov_status_keys.remove("FLASH_IFP_KEY_SLOT_STATUS%s" % (s))
                            del self.exp_prov_status["eFUSE_IFP_KEY_SLOT_STATUS%s" % (s)]
                            del self.exp_prov_status["FLASH_IFP_KEY_SLOT_STATUS%s" % (s)]

                        except: pass
                else:
                    prov_status_keys.remove("KEY_SLOT_B03_00_UAESKEY_0")
                    prov_status_keys.remove("KEY_SLOT_B11_08_OCSKEY_1")
                    prov_status_keys.remove("KEY_SLOT_B15_12")
                    prov_status_keys.remove("KEY_SLOT_B07_04_OCSKEY_0")
                    prov_status_keys.remove("KEY_SLOT_B19_16")
                    prov_status_keys.remove("KEY_SLOT_B23_20")
                    del self.exp_prov_status["KEY_SLOT_B03_00_UAESKEY_0"]
                    del self.exp_prov_status["KEY_SLOT_B11_08_OCSKEY_1"]
                    del self.exp_prov_status["KEY_SLOT_B15_12"]
                    del self.exp_prov_status["KEY_SLOT_B07_04_OCSKEY_0"]
                    del self.exp_prov_status["KEY_SLOT_B19_16"]
                    del self.exp_prov_status["KEY_SLOT_B23_20"]
 
                # check fields
                for slot in range(self.RH_SLOT_COUNT) :
                    _slot_cancellation_status = "OWNER_RH%s_CANC_STATUS" % (slot)
                    if (prov_status[_slot_cancellation_status] != self.exp_prov_status[_slot_cancellation_status]) :
                        err_msgs.append("ERROR :: %s value mismatched Measured = 0x%x and Expected = 0x%x" % (_slot_cancellation_status, prov_status[_slot_cancellation_status], self.exp_prov_status[_slot_cancellation_status]))
                        local_pass = False
                        
                for slot in range(prov_status['HASH_COUNT']+1) :
                    _owner_rh = "OWNER_RH%s" % (slot)
                    _owner_expkey_canc_status = "OWNER%s_EXPKEY_CANC_STATUS" % (slot)
                    if (prov_status[_owner_rh] != self.exp_prov_status[_owner_rh]) :
                        err_msgs.append("ERROR :: {} value mismatched Measured = {} and Expected = {}".format(_owner_rh, ', '.join(hex(x) for x in prov_status[_owner_rh]), ', '.join(hex(x) for x in self.exp_prov_status[_owner_rh])))
                        local_pass = False

                    if (prov_status[_owner_expkey_canc_status] != self.exp_prov_status[_owner_expkey_canc_status]) :
                        err_msgs.append("ERROR :: %s value mismatched Measured = 0x%x and Expected = 0x%x" % (_owner_expkey_canc_status, prov_status[_owner_expkey_canc_status], self.exp_prov_status[_owner_expkey_canc_status]))
                        local_pass = False
                
                for prov_status_key in prov_status_keys :
                    if (prov_status[prov_status_key] != self.exp_prov_status[prov_status_key]) :
                        err_msgs.append("ERROR :: %s value mismatched Measured = 0x%x and Expected = 0x%x" % (prov_status_key, prov_status[prov_status_key], self.exp_prov_status[prov_status_key]))
                        local_pass = False

                if (sdm_version != "1.5"):
                					
                    self.exp_prov_status["KEY_SLOT_B31_24"]                            = 0
                    self.exp_prov_status["KEY_SLOT_STATUS_B31_24"]                     = 0
                    self.exp_prov_status["FPM_CTR_VALUE"]                              = 0
                    self.exp_prov_status["OWNERSHIP_TRANSFER_MODE_STATUS"]             = 0
                    self.exp_prov_status["NUMBER_OF_OWNERSHIP_TRANSFER_OPPORTUNITIES"] = 0
                    for s in range(6) :
                        try:
                            self.exp_prov_status["eFUSE_IFP_KEY_SLOT_STATUS%s" % (s)]         = 1
                            self.exp_prov_status["FLASH_IFP_KEY_SLOT_STATUS%s" % (s)]  = 1							

                        except: pass					
                else:
                    self.exp_prov_status["KEY_SLOT_B03_00_UAESKEY_0"]                  = 0 
                    self.exp_prov_status["KEY_SLOT_B11_08_OCSKEY_1"]                   = 1 
                    self.exp_prov_status["KEY_SLOT_B15_12"]                            = 0 
                    self.exp_prov_status["KEY_SLOT_B07_04_OCSKEY_0"]                   = 1 
                    self.exp_prov_status["KEY_SLOT_B19_16"]                            = 0 
                    self.exp_prov_status["KEY_SLOT_B23_20"]                            = 0 

        else :
            return prov_status[key]

        if err_msgs :
            for err in err_msgs :
                print_err(err)
            if ast:
                assert_err(0, "ERROR :: PROV_STATUS incorrect")
            else:
                print_err("ERROR :: PROV_STATUS incorrect")
        else :
            cv_logger.info("PROV_STATUS result same as expectation")

        return local_pass

    '''
    Input   : cmf_state -- 1 we expect the device to be in CMF state, 0 means still in bootrom
              2 means it can be in either state (if in cmf state, will check against expected status.
              If bootrom stage, don't care)
              pr -- send config_status if False, send reconfig_status if True
              fpga -- send thru jtag if False, send thru fpga_mbox if True
              ast -- 0, we will not do any assertion, just return 0 if mismatch with expectation
              if ast=1, we will throw assertion error immediately when status mismatch
              pr_bad -- if False, check everything. If true, skip checks for CONFIG_DONE and INIT_DONE because it could be either or
              skip_ver -- skip version check of the firmware
    Mod     : self, calls the config_status command via jtag
    Require : only call this after verifying pin. There is one assumption that the pins are correct
    Output  : True if correct, False if incorrect
              Prints mismatching fields
    Note    : Checks all the status fields except 'ERROR_LOCATION', 'ERROR_DETAILS' (last 2)
    '''
    def verify_status(self, cmf_state=2, pr=False, ast=0, fpga=False, pr_bad=False, skip_ver=0):
        # if ND5 RevA and IDLE state
        if ((re.search('[Nn][Dd]5', self._BASE_DIE) != None) and (re.search('[aA]', self._REV) != None) and (self.exp_status['NCONFIG'] == 0) and (self.exp_status['NSTATUS'] == 0)):
            cv_logger.warning("ND5 RevA device cannot call CONFIG_STATUS/RECONFIG_STATUS at IDLE state. Skipping status verification!")
            return True

        if not fpga:
            if not pr:
                cv_logger.info("V%d :: Verify status" %(self._verify_counter))
                local_respond = self.jtag_send_sdmcmd(SDM_CMD['CONFIG_STATUS'])
                cv_logger.info("Send CONFIG_STATUS :: Response %s" %str(local_respond))
            else:
                cv_logger.info("V%d :: Verify reconfig status" %(self._verify_counter))
                local_respond = self.jtag_send_sdmcmd(SDM_CMD['RECONFIG_STATUS'])
                cv_logger.info("Send RECONFIG_STATUS :: Response %s" %str(local_respond))
        else:
            assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector before can verify status thru fpga connector")
            if not pr:
                cv_logger.info("V%d :: Verify status" %(self._verify_counter))
                self.fpga.write_command(SDM_CMD['CONFIG_STATUS'])
                local_respond = self.fpga_read_respond()
                cv_logger.info("Send CONFIG_STATUS :: Response %s" %str(local_respond))
            else:
                cv_logger.info("V%d :: Verify reconfig status" %(self._verify_counter))
                self.fpga.write_command(SDM_CMD['RECONFIG_STATUS'])
                local_respond = self.fpga_read_respond()
                cv_logger.info("Send RECONFIG_STATUS :: Response %s" %str(local_respond))

        self._verify_counter = self._verify_counter + 1

        default_val   = 0xFEABD

        #Dictionary holding the config_status
        config_status  = {
                           'STATE'            : default_val,
                           'VERSION'          : default_val,
                           'NSTATUS'          : default_val,
                           'NCONFIG'          : default_val,
                           'MSEL_LATCHED'     : default_val,
                           'CONFIG_DONE'      : default_val,
                           'INIT_DONE'        : default_val,
                           'CVP_DONE'         : default_val,
                           'SEU_ERROR'        : default_val,
                           'ERROR_LOCATION'   : default_val,
                           'ERROR_DETAILS'    : default_val,
                           'POR_WAIT'         : default_val,
                           'TRAMP_DSBLE'      : default_val,
                           'BETALOADER'       : default_val,
                           'PROVISION_CMF'    : default_val,
                        }

        #First Check the Length of List received
        local_lst_length = len(local_respond)
        local_pass = True
        err_msgs = []

        #assert if really in cmf_state or not. if this is wrong, no point continue the test
        if (cmf_state == 0):
            #Added by SatyaS to Handle FMx Bootrom processing which returns 4 Words response
            #First Word <> length of data followed; Second <> Bootrom Version, Third <> Bootrom State and Fourth <> Bootrom MSEL, nCONFIG, nSTATUS etc latching
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                assert_err(local_lst_length == 4, "ERROR :: Expected device at Bootrom stage.\nCONFIG_STATUS should return 4 elements, but received %d" %local_lst_length)
                local_extract = int(local_respond[3])
                nstatus = (local_extract >> 31) & 0x00000001
                nconfig = (local_extract >> 30) & 0x00000001
                avst_ready = (local_extract >> 29) & 0x00000001
                active_msel = (local_extract >> 4) & 0x0000000f
                por_msel = local_extract & 0x0000000f

                cv_logger.info("nSTATUS = %d" %nstatus)
                cv_logger.info("nCONFIG = %d" %nconfig)
                cv_logger.info("AVST READY = %d" %avst_ready)
                cv_logger.info("Active msel = %d" %active_msel)
                cv_logger.info("POR msel = %d" %por_msel)
            else:
                assert_err(local_lst_length == 2, "ERROR :: Expected device at Bootrom stage.\nCONFIG_STATUS should return 2 elements, but received %d" %local_lst_length)
            cv_logger.info("CONFIG_STATUS now in bootrom stage as expected")
        elif (cmf_state == 1 or (cmf_state == 2  and local_lst_length != 2)):
            if local_lst_length == 4:
                local_extract = int(local_respond[3])
                nstatus = (local_extract >> 31) & 0x00000001
                nconfig = (local_extract >> 30) & 0x00000001
                avst_ready = (local_extract >> 29) & 0x00000001
                active_msel = (local_extract >> 4) & 0x0000000f
                por_msel = local_extract & 0x0000000f

                cv_logger.info("nSTATUS = %d" %nstatus)
                cv_logger.info("nCONFIG = %d" %nconfig)
                cv_logger.info("AVST READY = %d" %avst_ready)
                cv_logger.info("Active msel = %d" %active_msel)
                cv_logger.info("POR msel = %d" %por_msel)

            local_extract_header = int(local_respond[0])

            'Header info gives Number of Elements*4096'
            local_number_element = local_extract_header/4096

            assert_err(((local_lst_length-1) == local_number_element), "ERROR :: Expected device in CMF stage.\nExpected Length as per header = %d, but receieved length = %d" %(local_number_element, (local_lst_length-1)))

            # Define current acds version & build
            acds_version = os.environ["ACDS_VERSION"]
            acds_build = float(os.environ["ACDS_BUILD_NUMBER"])

            # Define the affected version and build
            self.expected_acds = { "21.4.1" : 99,
                                   "22.1"   : 96,
                                  }

            #Extract the values and fill the local dictionary
            local_counter = 0
            for element in local_respond:
                if(local_counter == 1):
                    config_status['STATE']             = int(element)

                elif(local_counter == 2):
                    config_status['VERSION']           = int(element)

                elif(local_counter == 3):
                    config_status['NSTATUS']           = int(getbitvalue(element,31))
                    config_status['NCONFIG']           = int(getbitvalue(element,30))

                    # 21.4.1/97 ++
                    # 22.1/96 ++
                    if ((acds_version == "22.1" and acds_build >= self.expected_acds["22.1"]) or (acds_version > "22.1")) and not self.DUT_FAMILY == "stratix10":
                        config_status['MSEL_LATCHED']      = int(getbitvalue(element,3,0))
                    elif ((acds_version == "21.4.1" and acds_build >= self.expected_acds["21.4.1"]) or (acds_version > "21.4.1")) and not self.DUT_FAMILY == "stratix10":
                        config_status['MSEL_LATCHED']      = int(getbitvalue(element,3,0))
                    else:
                        config_status['MSEL_LATCHED']      = int(getbitvalue(element,7,0))

                    config_status['VID_ENABLE']        = int(getbitvalue(element,4))
                    config_status['TEST_MODE']         = int(getbitvalue(element,5))
                    config_status['PLL_MODE']          = int(getbitvalue(element,7,6))

                elif(local_counter == 4):
                    config_status['CONFIG_DONE']       = int(getbitvalue(element,0))
                    config_status['INIT_DONE']         = int(getbitvalue(element,1))
                    config_status['CVP_DONE']          = int(getbitvalue(element,2))
                    config_status['SEU_ERROR']         = int(getbitvalue(element,3))
                    config_status['POR_WAIT']          = int(getbitvalue(element,6))
                    config_status['TRAMP_DSBLE']       = int(getbitvalue(element,7))
                    config_status['BETALOADER']        = int(getbitvalue(element,30))
                    config_status['PROVISION_CMF']     = int(getbitvalue(element,31))

                elif(local_counter == 5):
                    config_status['ERROR_LOCATION']    = int(element)

                elif(local_counter == 6):
                    config_status['ERROR_DETAILS']     = int(element)

                local_counter = local_counter + 1

            cv_logger.info("(re)config_status['STATE']              = 0x%x" %config_status['STATE'])
            cv_logger.info("(re)config_status['VERSION']            = 0x%x" %config_status['VERSION'])
            cv_logger.info("(re)config_status['NSTATUS']            = 0x%x" %config_status['NSTATUS'])
            cv_logger.info("(re)config_status['NCONFIG']            = 0x%x" %config_status['NCONFIG'])

            if ((acds_version == "22.1" and acds_build >= self.expected_acds["22.1"]) or (acds_version > "22.1")) and not self.DUT_FAMILY == "stratix10":
                cv_logger.info("(re)config_status['VID_ENABLE']         = 0x%x" %config_status['VID_ENABLE'])
                cv_logger.info("(re)config_status['TEST_MODE']          = 0x%x" %config_status['TEST_MODE'])
                cv_logger.info("(re)config_status['PLL_MODE']           = 0x%x" %config_status['PLL_MODE'])
            elif ((acds_version == "21.4.1" and acds_build >= self.expected_acds["21.4.1"]) or (acds_version > "21.4.1")) and not self.DUT_FAMILY == "stratix10":
                cv_logger.info("(re)config_status['VID_ENABLE']         = 0x%x" %config_status['VID_ENABLE'])
                cv_logger.info("(re)config_status['TEST_MODE']          = 0x%x" %config_status['TEST_MODE'])
                cv_logger.info("(re)config_status['PLL_MODE']           = 0x%x" %config_status['PLL_MODE'])

            cv_logger.info("(re)config_status['MSEL_LATCHED']       = 0x%x" %config_status['MSEL_LATCHED'])
            cv_logger.info("(re)config_status['CONFIG_DONE']        = 0x%x" %config_status['CONFIG_DONE'])
            cv_logger.info("(re)config_status['INIT_DONE']          = 0x%x" %config_status['INIT_DONE'])
            cv_logger.info("(re)config_status['CVP_DONE']           = 0x%x" %config_status['CVP_DONE'])
            cv_logger.info("(re)config_status['SEU_ERROR']          = 0x%x" %config_status['SEU_ERROR'])
            cv_logger.info("(re)config_status['POR_WAIT']           = 0x%x" %config_status['POR_WAIT'])
            cv_logger.info("(re)config_status['TRAMP_DSBLE']        = 0x%x" %config_status['TRAMP_DSBLE'])
            cv_logger.info("(re)config_status['BETALOADER']         = 0x%x" %config_status['BETALOADER'])
            cv_logger.info("(re)config_status['PROVISION_CMF']      = 0x%x" %config_status['PROVISION_CMF'])
            cv_logger.info("(re)config_status['ERROR_LOCATION']     = 0x%x" %config_status['ERROR_LOCATION'])
            cv_logger.info("(re)config_status['ERROR_DETAILS']      = 0x%x" %config_status['ERROR_DETAILS'])

            cv_logger.info("Comparing (re)config_status with expectation...")

            #check all fields except the last 2
            if (self.exp_status['STATE'] == 1):
                if(config_status['STATE'] == 0 ):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['STATE'], self.exp_status['STATE']))
                    local_pass = False
            elif (self.exp_status['STATE'] == "dc"):
                pass
            elif (self.exp_status['STATE'] == "error"):
                if( (config_status['STATE'] == 0) or (config_status['STATE'] == 0x10000000)):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = %s" %(config_status['STATE'], self.exp_status['STATE']))
                    local_pass = False
            elif (self.exp_status['STATE'] == "noerror"):
                if( (config_status['STATE'] != 0) and (config_status['STATE'] != 0x10000000)):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = %s" %(config_status['STATE'], self.exp_status['STATE']))
                    local_pass = False
            else:
                if(config_status['STATE'] != self.exp_status['STATE']):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['STATE'], self.exp_status['STATE']))
                    local_pass = False

            # Bypass VERSION checking if it is Simics until the fwval_lib is ready for FW latest version feature
            if os.environ.get("PYCV_PLATFORM") != "simics" :
                if(config_status['VERSION'] != self.exp_status['VERSION'] and not skip_ver):
                    err_msgs.append("ERROR :: VERSION value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['VERSION'], self.exp_status['VERSION']))
                    local_pass = False

            if(config_status['NSTATUS'] != self.exp_status['NSTATUS']):
                err_msgs.append("ERROR :: NSTATUS value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['NSTATUS'], self.exp_status['NSTATUS']))
                local_pass = False

            if(config_status['NCONFIG'] != self.exp_status['NCONFIG']):
                err_msgs.append("ERROR :: NCONFIG value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['NCONFIG'], self.exp_status['NCONFIG']))
                local_pass = False

            if(config_status['MSEL_LATCHED'] != self.exp_status['MSEL_LATCHED']):
                err_msgs.append("ERROR :: MSEL value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['MSEL_LATCHED'], self.exp_status['MSEL_LATCHED']))
                local_pass = False

            if not pr_bad:
                if(config_status['CONFIG_DONE'] != self.exp_status['CONFIG_DONE']):
                    err_msgs.append("ERROR :: CONFIG_DONE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['CONFIG_DONE'], self.exp_status['CONFIG_DONE']))
                    local_pass = False

                if(config_status['INIT_DONE'] != self.exp_status['INIT_DONE']):
                    err_msgs.append("ERROR :: INIT_DONE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['INIT_DONE'], self.exp_status['INIT_DONE']))
                    local_pass = False
            else:
                cv_logger.info("skip checks for CONFIG_DONE and INIT_DONE for PR bad case")

            if(config_status['CVP_DONE'] != self.exp_status['CVP_DONE']):
                err_msgs.append("ERROR :: CVP_DONE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['CVP_DONE'], self.exp_status['CVP_DONE']))
                local_pass = False

            if os.environ.get("PYCV_PLATFORM") != "simics" :
                if(config_status['SEU_ERROR'] != self.exp_status['SEU_ERROR']):
                    err_msgs.append("ERROR :: SEU_ERROR value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['SEU_ERROR'], self.exp_status['SEU_ERROR']))
                    for count in range (0,10):
                        cv_logger.info("***************************************************")
                        cv_logger.info("Read SEU ERROR counter: %d" %(count))
                        local_respond = self.jtag_send_sdmcmd(SDM_CMD['READ_SEU_ERROR'])
                        cv_logger.info("Read SEU ERROR :: Response %s" %str(local_respond))
                        cv_logger.info("***************************************************")
                    local_pass = False

            if(config_status['POR_WAIT'] != self.exp_status['POR_WAIT']):
                err_msgs.append("ERROR :: POR_WAIT value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['POR_WAIT'], self.exp_status['POR_WAIT']))
                local_pass = False

            if(config_status['TRAMP_DSBLE'] != self.exp_status['TRAMP_DSBLE']):
                err_msgs.append("ERROR :: TRAMP_DSBLE value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['TRAMP_DSBLE'], self.exp_status['TRAMP_DSBLE']))
                local_pass = False

            if(config_status['BETALOADER'] != self.exp_status['BETALOADER']):
                err_msgs.append("ERROR :: BETALOADER value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['BETALOADER'], self.exp_status['BETALOADER']))
                local_pass = False

            if(config_status['PROVISION_CMF'] != self.exp_status['PROVISION_CMF']):
                err_msgs.append("ERROR :: PROVISION_CMF value mismatched Measured = 0x%x and Expected = 0x%x" %(config_status['PROVISION_CMF'], self.exp_status['PROVISION_CMF']))
                local_pass = False

        else:
            cv_logger.warning("Device in Bootrom stage, but user indicated don't care.")

        if err_msgs:
            for err in err_msgs:
                print_err(err)
            if ast:
                assert_err(0, "ERROR :: (RE)CONFIG_STATUS incorrect")
            else:
                print_err("ERROR :: (RE)CONFIG_STATUS incorrect")
        else:
            cv_logger.info("(RE)CONFIG_STATUS result same as expectation")

        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            cv_logger.info("Wait 100s")
            delay(100000)

        return local_pass

    '''
    Input   : nconfig, nstatus, config_done, init_done, avst_ready, cvp_done. 0 or 1
              operation -- Expect a dictionary to define the exp_status key to perform operation (Eg: logical/bitwise operation)
                           Eg: update_exp(version=0, operation={"VERSION" : "| 1 << 5"})
    Optional: All inputs are optional, only update the expectation of signals that you specifiy
    Modify  : updates the exp_pin and exp_status for self
    Note    :
    '''
    def update_exp(self, state=None, version=None, nconfig=None, nstatus=None, config_done=None, init_done=None, avst_ready=None, cvp_done=None, msel=None, por_wait=None, provision_cmf=None, tramp_dsble=None, seu_error=None, betaloader=None, **kwargs):
        cv_logger.info("Updating expectations...")
        if state != None:
            self.exp_status['STATE'] = state
        if version != None:
            self.exp_status['VERSION'] = version
        if nconfig != None:
            self.exp_status['NCONFIG'] = nconfig
        if nstatus != None:
            self.exp_status['NSTATUS'] = nstatus
            self.exp_pin['NSTATUS'] = nstatus
        if config_done != None:
            self.exp_status['CONFIG_DONE'] = config_done
            self.exp_pin['CONFIG_DONE'] = config_done
        if init_done != None:
            self.exp_status['INIT_DONE'] = init_done
            self.exp_pin['INIT_DONE'] = init_done
        if avst_ready != None:
            self.exp_pin['AVST_READY'] = avst_ready
        if cvp_done != None:
            self.exp_status['CVP_DONE'] = cvp_done
        if msel != None:
            self.exp_status['MSEL_LATCHED'] = msel
        if por_wait != None:
            self.exp_status['POR_WAIT'] = por_wait
        if tramp_dsble != None:
            self.exp_status['TRAMP_DSBLE'] = tramp_dsble
        if betaloader != None:
            self.exp_status['BETALOADER'] = betaloader
        if provision_cmf != None:
            self.exp_status['PROVISION_CMF'] = provision_cmf
        if seu_error != None:
            # WDT will report timeout using SEU_ERROR. Added 21.2+
            self.exp_status['SEU_ERROR'] = seu_error

        # If user pass operation argument, update the config status expectation with valid operation
        self.update_exp_operation(**kwargs)

        cv_logger.info("Expectations updated")

    '''
    Input   : operation -- Expect a dictionary to define the exp_status key to perform operation (Eg: logical/bitwise operation)
                           Eg: update_exp(version=0, operation={"VERSION" : "| 1 << 5"})
    Optional: All inputs are optional, only update the expectation of signals that you specifiy
    Modify  : updates the exp_pin and exp_status for self
    Note    : Not to use this internal function directly, just pass kwargs to self.update_exp()
              "check_file_version" option is usually required for trampoline test to check the programming file version and update the version expectation
    '''
    def update_exp_operation(self, **kwargs):
        if kwargs.get("operation"):
            for key,operation in kwargs["operation"].items():
                # Update version expectation based on programming file
                if key.lower() == "check_file_version":
                    if self.DUT_FILTER.dut_codename in self.expected_device:
                        cv_logger.info("Update version expectation by checking programming file's version and build number of {}".format(kwargs['operation']['check_file_version']))
                        nadderdump_txt = "dumper.txt"

                        programming_file = kwargs["operation"]["check_file_version"]

                        # Need to revisit below methods in 21.4 as quartus_pfg support the reading of cmf's version/build information
                        # New feature request to show Quartus tool version HSD #1509648608
                        # if re.search(r"\.rbf$",programming_file):
                        #     cv_logger.info("Get CMF's version and build by using nadderdump")
                        #     run_nadderdump_command("--truncate -hidedata %s" % programming_file, nadderdump_txt=nadderdump_txt)

                        #     with open(nadderdump_txt,"r") as f:
                        #         dump_file = f.read()

                        #     version_number = re.search(r"version=(\S+),",dump_file)
                        #     build_number = re.search(r"buildnum=(\S+),",dump_file)
                        #     if version_number:
                        #         version_number = version_number.group(1)
                        #     else:
                        #         cv_logger.warning("version_number is not detected")

                        #     if build_number:
                        #         build_number = int(build_number.group(1))
                        #     else:
                        #         cv_logger.warning("build_number is not detected")

                        #     os.remove(nadderdump_txt)
                        # else:

                        # Try to grep fw version/build info from standard sof name
                        cv_logger.info("Get CMF's version and build by checking its standard file name")
                        is_name = re.search(r"\.fw-(\d+(\.\d+)+)_b(\d+)",programming_file)
                        if is_name:
                            version_number = is_name.group(1)
                            build_number = int(is_name.group(3))
                        else:
                            cv_logger.warning("Both version_number and build_number are not detected from file name")

                        cv_logger.info("Version: {}, Build: {}".format(version_number,build_number))

                        if version_number is None or build_number is None:
                            cv_logger.warning("Not updating the version expectation as either version or build are not found")
                        else:
                            if not ((version_number == self.expected_acds_version and build_number >= self.expected_acds_build) or (version_number > self.expected_acds_version)):
                                cv_logger.info("Reset the config status's version expectation exp_status[\"VERSION\"][23:0] to 0 as older firmware has different expectation")
                                self.update_exp(operation={"VERSION" : "& 0xFF000000"})
                            else:
                                self.exp_status["VERSION"] = self.get_expected_version(acds_version=version_number, acds_build=build_number)
                        cv_logger.info("Expected sdm fw version: {}".format(hex(self.exp_status["VERSION"])))
                # Process any other key and value pair
                else:
                    try:
                        self.exp_status[key.upper()] = eval("self.exp_status['{}'] {}".format(key.upper(),operation))
                    except KeyError as e:
                        cv_logger.warning("{} not found in exp_status".format(e))
                    except SyntaxError as e:
                        error_msg = "ERROR :: Invalid operation to update exp_status['{}']".format(key.upper())
                        cv_logger.warning(error_msg)
                        assert_err(0,error_msg)

    '''
    Input   : None
    Note    : Return expected_acds_version dynamically for config status's version expectation
    '''
    def get_expected_version(self, acds_version=None, acds_build=None):
        if acds_version is None:
            acds_version = os.environ["ACDS_VERSION"]

        if acds_build is None:
            acds_build = float(os.environ["ACDS_BUILD_NUMBER"])

        # Remove any alphabets
        acds_version = re.sub(r"[aA-zZ]+","",acds_version)

        # Define the affected device, version and build
        self.expected_device = ["falconmesa","diamondmesa","sundancemesa"]
        self.expected_acds_version = "21.3"
        self.expected_acds_build = 127

        # Obtain the expected ACDS version expectation dynamically if the conditions are met
        if ((acds_version == self.expected_acds_version and acds_build >= self.expected_acds_build) or (acds_version > self.expected_acds_version)) and self.DUT_FILTER.dut_codename in self.expected_device:
            release_numbers = acds_version.split(".")

            # Store the major and minor ACDS release numbers
            acds_rel_dict = {
                "major" : int(release_numbers[0]),
                "minor" : int(release_numbers[1]),
            }

            # Store update number if exist
            if len(release_numbers) == 3:
                acds_rel_dict["update"] = int(release_numbers[2])

            # Perform bitwise operation to match the config status's version expectation return by SDM FW
            expected_acds_version = 0 | acds_rel_dict["major"] << 16 | acds_rel_dict["minor"] << 8

            # Append update number if exist
            if acds_rel_dict.get("update"):
                expected_acds_version |= acds_rel_dict["update"]
        else:
            # Return 0 for older ACDS version
            expected_acds_version = 0

        return expected_acds_version

    '''
    Input   : see input arguments
    Optional: All inputs are optional, only update the expectation of signals that you specifiy
    Device  : FM6, DMD support 3 slots while FM7 and above support 5 slots
    Modify  : updates the exp_prov_status for self
    Note    : values like HASH_TYPE should always be 2, so no update for expectation required
    '''
    def update_prov_exp(self, skip_prov=None, prov_status=None, intel_status=None, cosign=None, hash_count=None,
        slot0_status=None, slot1_status=None, slot2_status=None, slot3_status=None, slot4_status=None,
        slot0_hash=None, slot0_keyid_status=None, slot1_hash=None, slot1_keyid_status=None,
        slot2_hash=None, slot2_keyid_status=None, slot3_hash=None, slot3_keyid_status=None,
        slot4_hash=None, slot4_keyid_status=None, pts_base=None, pts_counter=None,
        svn3=None, svn2=None, svn1=None, svn0=None):

        cv_logger.info("Updating prov expectations...")
        if skip_prov != None:
            self.exp_prov_status['SKIP_PROV_CMD'] = skip_prov
            cv_logger.debug("Update exp_prov_status[SKIP_PROV_CMD]=%s" % (skip_prov))
        if prov_status != None:
            self.exp_prov_status['PROV_STATUS_CODE'] = prov_status
            cv_logger.debug("Update exp_prov_status[PROV_STATUS_CODE]=%s" % (prov_status))
        if intel_status != None:
            self.exp_prov_status['INTEL_CANC_STATUS'] = intel_status
            cv_logger.debug("Update exp_prov_status[INTEL_CANC_STATUS]=%s" % (intel_status))
        if cosign != None:
            self.exp_prov_status['COSIGN_STATUS'] = cosign
            cv_logger.debug("Update exp_prov_status[COSIGN_STATUS]=%s" % (cosign))
        if slot0_status != None:
            self.exp_prov_status['OWNER_RH0_CANC_STATUS'] = slot0_status
            cv_logger.debug("Update exp_prov_status[OWNER_RH0_CANC_STATUS]=%s" % (slot0_status))
        if slot1_status != None:
            self.exp_prov_status['OWNER_RH1_CANC_STATUS'] = slot1_status
            cv_logger.debug("Update exp_prov_status[OWNER_RH1_CANC_STATUS]=%s" % (slot1_status))
        if slot2_status != None:
            self.exp_prov_status['OWNER_RH2_CANC_STATUS'] = slot2_status
            cv_logger.debug("Update exp_prov_status[OWNER_RH2_CANC_STATUS]=%s" % (slot2_status))
        if slot3_status != None:
            self.exp_prov_status['OWNER_RH3_CANC_STATUS'] = slot3_status
            cv_logger.debug("Update exp_prov_status[OWNER_RH3_CANC_STATUS]=%s" % (slot3_status))
        if slot4_status != None:
            self.exp_prov_status['OWNER_RH4_CANC_STATUS'] = slot4_status
            cv_logger.debug("Update exp_prov_status[OWNER_RH4_CANC_STATUS]=%s" % (slot4_status))
        if hash_count != None:
            self.exp_prov_status['HASH_COUNT'] = hash_count
            cv_logger.debug("Update exp_prov_status[HASH_COUNT]=%s" % (hash_count))
        if slot0_hash != None:
            self.exp_prov_status['OWNER_RH0'] = slot0_hash
            cv_logger.debug("Update exp_prov_status[OWNER_RH0]={}".format(','.join(hex(x) for x in slot0_hash)))
        if slot0_keyid_status != None:
            self.exp_prov_status['OWNER0_EXPKEY_CANC_STATUS'] = slot0_keyid_status
        if slot1_hash != None:
            self.exp_prov_status['OWNER_RH1'] = slot1_hash
            cv_logger.debug("Update exp_prov_status[OWNER_RH1]={}".format(','.join(hex(x) for x in slot1_hash)))
        if slot1_keyid_status != None:
            self.exp_prov_status['OWNER1_EXPKEY_CANC_STATUS'] = slot1_keyid_status
        if slot2_hash != None:
            self.exp_prov_status['OWNER_RH2'] = slot2_hash
            cv_logger.debug("Update exp_prov_status[OWNER_RH2]={}".format(','.join(hex(x) for x in slot2_hash)))
        if slot2_keyid_status != None:
            self.exp_prov_status['OWNER2_EXPKEY_CANC_STATUS'] = slot2_keyid_status
            cv_logger.debug("Update exp_prov_status[OWNER2_EXPKEY_CANC_STATUS]=%s" % (slot2_keyid_status))
        if slot3_hash != None:
            self.exp_prov_status['OWNER_RH3'] = slot3_hash
            cv_logger.debug("Update exp_prov_status[OWNER_RH3]={}".format(','.join(hex(x) for x in slot3_hash)))
        if slot3_keyid_status != None:
            self.exp_prov_status['OWNER3_EXPKEY_CANC_STATUS'] = slot3_keyid_status
        if slot4_hash != None:
            self.exp_prov_status['OWNER_RH4'] = slot4_hash
            cv_logger.debug("Update exp_prov_status[OWNER_RH4]={}".format(','.join(hex(x) for x in slot4_hash)))
        if slot4_keyid_status != None:
            self.exp_prov_status['OWNER4_EXPKEY_CANC_STATUS'] = slot4_keyid_status
        if pts_base != None:
            self.exp_prov_status['BIG_COUNTER_BASE'] = pts_base
            cv_logger.debug("Update exp_prov_status[BIG_COUNTER_BASE]=%s" % (pts_base))
        if pts_counter != None:
            self.exp_prov_status['BIG_COUNTER'] = pts_counter
            cv_logger.debug("Update exp_prov_status[BIG_COUNTER]=%s" % (pts_counter))
        if svn3 != None:
            self.exp_prov_status['SVN3'] = svn3
            cv_logger.debug("Update exp_prov_status[SVN3]=%s" % (svn3))
        if svn2 != None:
            self.exp_prov_status['SVN2'] = svn2
            cv_logger.debug("Update exp_prov_status[SVN2]=%s" % (svn2))
        if svn1 != None:
            self.exp_prov_status['SVN1'] = svn1
            cv_logger.debug("Update exp_prov_status[SVN1]=%s" % (svn1))
        if svn0 != None:
            self.exp_prov_status['SVN0'] = svn0
            cv_logger.debug("Update exp_prov_status[SVN0]=%s" % (svn0))

        cv_logger.info("Prov expectations updated")

    '''
    Input   : see input arguments
    Optional: All inputs are optional, only update the expectation of signals that you specifiy
    Modify  : updates the _scoreboard_state dict for self
    Note    : for manual syncing _scoreboard_state internal variable with CMF
    '''
    def update_scoreboard_state(self, sec_owner_auth_flag=None, **kwargs) :

        cv_logger.info("Updating _scoreboard_state expectations...")
        
        # legacy pr_auth_flag. renamed to sec_owner_auth_flag
        if kwargs.get("pr_auth_flag", None) != None:
            cv_logger.warning("pr_auth_flag is renamed to sec_owner_auth_flag (since 24.1). please update test content")
            sec_owner_auth_flag = kwargs.get("pr_auth_flag")
        
        # sec_owner_auth_flag supersede pr_auth_flag
        if sec_owner_auth_flag != None:
            self._scoreboard_state['sec_owner_auth_flag'] = sec_owner_auth_flag
            cv_logger.info("Update _scoreboard_state[sec_owner_auth_flag]=%s" % (self._scoreboard_state['sec_owner_auth_flag']))

        # clear secondary_ownership_pk to enable coming secondary_pubkey_program
        if kwargs.get("secondary_ownership_pk") != None:
            self._scoreboard_state['secondary_ownership_pk'] = kwargs.get("secondary_ownership_pk")
            cv_logger.info("Update _scoreboard_state[secondary_ownership_pk]=%s" % (self._scoreboard_state['secondary_ownership_pk']))
            
        cv_logger.info("_scoreboard_state expectations updated")

    '''
    Input   : nconfig, nstatus, config_done, init_done, avst_ready, cvp_done. 0 or 1
              operation -- Expect a dictionary to define the exp_status key to perform operation (Eg: logical/bitwise operation)
                           Eg: update_exp(version=0, operation={"VERSION" : "| 1 << 5"})
    Optional: All inputs are optional, only update the expectation of signals that you specifiy
    Modify  : updates the exp_pin and exp_status for self
    Note    :
    '''
    def update_exp_rsu(self, state=None, version=None, current_image=None, last_fail_image=None, **kwargs):
        cv_logger.info("Updating expectations for rsu_status...")

        if state != None:
            self.exp_rsu_status['STATE'] = state
            cv_logger.info("Update exp_rsu_status['STATE'] to %s" %state)
        if version != None:
            self.exp_rsu_status['VERSION'] = version
            cv_logger.info("Update exp_rsu_status['VERSION'] to %s" %version)
        if current_image != None:
            current_image_0 = current_image & 0xffffffff
            current_image_1 = (current_image >>32) & 0xffffffff
            self.exp_rsu_status['CURRENT_IMAGE_0'] = current_image_0
            self.exp_rsu_status['CURRENT_IMAGE_1'] = current_image_1
            cv_logger.info("Update exp_rsu_status['CURRENT_IMAGE_0'] to 0X%08X" %current_image_0)
            cv_logger.info("Update exp_rsu_status['CURRENT_IMAGE_1'] to 0X%08X" %current_image_1)
        if last_fail_image != None:
            last_fail_image_0 = last_fail_image & 0xffffffff
            last_fail_image_1 = (last_fail_image >>32) & 0xffffffff
            self.exp_rsu_status['LAST_FAIL_IMAGE_0'] = last_fail_image_0
            self.exp_rsu_status['LAST_FAIL_IMAGE_1'] = last_fail_image_1
            cv_logger.info("Update exp_rsu_status['LAST_FAIL_IMAGE_0'] to 0X%08X" %last_fail_image_0)
            cv_logger.info("Update exp_rsu_status['LAST_FAIL_IMAGE_1'] to 0X%08X" %last_fail_image_1)

        # If user pass operation argument, update the config status expectation with valid operation
        self.update_exp_operation(**kwargs)

        cv_logger.info("Expectations for rsu_status updated")

    '''
    Input   : file_path -- path for the bitstream file (usually rbf file)
    Output  : returns the file as a byte array
    Exception: Throws IOError if file not found, or file is empty
    '''
    def read_bitstream(self, file_path):
        cv_logger.info("Reading Bitstream")
        with open(file_path, "rb") as file:
            if(not file):
                print_err("ERROR :: Failed to Open the file %s" %file)
                raise IOError
            else:
                cv_logger.info("Opening file ==> %s successfully to read the bitstream content" %file_path )

            bitstream_buffer        = bytearray(file.read())
            bitstream_buffer_size   = len(bitstream_buffer)
            if(bitstream_buffer_size == 0):
                print_err("ERROR :: Source File %s size is empty" %file_path)
                raise IOError

        return bitstream_buffer

    '''
    Input   :   bitstream -- bytearray of the bitstream
                file_path -- the bitstream filename generated by the bitstream(usually rbf file)
    Exception: Throws IOError if file not found, or file is empty
    '''
    def write_bitstream_to_file(self, bitstream=None, start=0, end=None, file_path=None):
        cv_logger.info("Writing Bitstream from %d to %d to File %s"%(start, end, file_path))
        file = open(file_path, "wb")
        if(not file):
            print_err("ERROR :: Failed to Open the file %s to write" %file)
            raise IOError
        else:
            cv_logger.info("Opening file ==> %s successfully to write the bitstream content" %file_path )

        bitstream_buffer_size   = len(bitstream)
        if(bitstream_buffer_size == 0):
            print_err("ERROR :: Bitstream bytearray size is empty")
            file.close()
            raise IOError

        file.write(bitstream[start:end])
        file.close()
    '''
    Modify:
    Note: To write source data via ISSP connector
    Input: issp_index = the issp index.
            data = the data you want to write via ISSP
    Output:
    '''
    def issp_write_source_data(self, issp_index, data):

        cv_logger.info("Issp index chosen is : %d" %issp_index)
        cv_logger.info("Data to be sent is : 0x%x" %data)


        if issp_index == 0 :
            self.issp0 = self.dut.get_connector("issp", 0)
            assert_err(self.issp0 != None, "ERROR :: Cannot open ISSP index 0 Connector")
            source_value = self.issp0.read_source_data()
            cv_logger.info("Read original source data is " +str(source_value))
            cv_logger.info("Writing source data with 0x%x" %data)
            self.issp0.write_source_data(data)
            source_value = self.issp0.read_source_data()
            cv_logger.info("Read source data after write_source_data is " +str(source_value))


        elif issp_index == 1 :
            self.issp1 = self.dut.get_connector("issp", 1)
            assert_err(self.issp1 != None, "ERROR :: Cannot open ISSP index 1 Connector")
            source_value = self.issp1.read_source_data()
            cv_logger.info("Read original source data is " +str(source_value))
            cv_logger.info("Writing source data with 0x%x" %data)
            self.issp1.write_source_data(data)
            source_value = self.issp1.read_source_data()
            cv_logger.info("Read source data after write_source_data is " +str(source_value))


        else:
            cv_logger.info("Please provide issp index number!")


    '''
    Modify  : self, sends CONFIG_JTAG command
    '''
    def config_jtag(self, success=1):
        cv_logger.info("")
        local_respond = [None]
        try:
            timeout = 60
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
                timeout = 5000
            local_respond = self.jtag.packet_send_cmd(32, SDM_CMD['CONFIG_JTAG'], timeout=timeout)

        except Exception as e:
            if success:
                assert_err(0, "ERROR :: CONFIG_JTAG command failed unexpectedly")
            else:
                cv_logger.info("CONFIG_JTAG command failed as EXPECTED")
            return local_respond

        cv_logger.info("Send CONFIG_JTAG :: Response " + str(local_respond))

        if (local_respond[0] != 0) or (local_respond[0] == None):
            if success:
                assert_err(local_respond[0] == 0, "ERROR :: CONFIG_JTAG reponse is not [0]!")
            else:
                cv_logger.info("CONFIG_JTAG command failed as EXPECTED")

        else:
            if success:
                cv_logger.info("CONFIG_JTAG Command passed as EXPECTED")
            else:
                assert_err(local_respond[0] != 0, "ERROR :: The error code is 0, expected non-zero")

        # clear sec_owner_auth_flag whenever reconfig per vab spec
        self.update_scoreboard_state(sec_owner_auth_flag=0)


    '''
    Modify  : self, sends RECONFIG command via JTAG
    Note    : this command is not for full reconfiguration, it is for PR!
    '''
    def reconfig_jtag(self):
        cv_logger.info("")
        try:
            local_respond = self.jtag.packet_send_cmd(32, SDM_CMD['RECONFIG'])
        except:
            assert_err(0, "ERROR :: RECONFIG (PR) command failed")
        cv_logger.info("Send RECONFIG (PR) :: Response " + str(local_respond))

    '''
    Modify  : self, sends cancel command via JTAG
    Note    : this command is for PR cancel
    '''
    def jtag_send_cancel(self):
        cv_logger.info("")
        try:
            local_respond = self.jtag.packet_send_cmd(32, SDM_CMD['CANCEL'])
        except:
            assert_err(0, "ERROR :: CANCEL command failed")
        cv_logger.info("Send CANCEL command :: Response " +str(local_respond))

    '''
    Modify  : self, sends SDM command via JTAG
    Note    : this command is to switch RSU image
    '''
    def jtag_send_sdmcmd(self, sdm_cmd, *arg):
        input_length = len(arg)
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = sdm_cmd
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        timeout = 60
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout = 240
        cv_logger.info("===jtag_send_sdmcmd command===")
        cv_logger.info("header: [" + str(hex(header)) + "]")
        cv_logger.info("body  : " + '[{}]'.format(' '.join(hex(x) for x in arg)))
        cv_logger.info("===jtag_send_sdmcmd command===")
        resp = self.jtag.packet_send_cmd(32, header, *arg, timeout=timeout)
        self.jtag.unclaim_services(service="packet")
        cv_logger.info("===jtag_send_sdmcmd response===")
        if isinstance(resp, list):
            cv_logger.info("response: " + '[{}]'.format(' '.join(hex(x) for x in resp)))
        else:
            cv_logger.info("response: " + str(resp))
        cv_logger.info("===jtag_send_sdmcmd response===")
        return resp
    
    '''
    Modify  : self, sends SDM command via JTAG
    Note    : this command is send sdm cmd and check fw with noop and sync
    '''
    def jtag_send_sdmcmd_noop(self, sdm_cmd, *arg):
        input_length = len(arg)
        input_id = 0 #does not matter
        input_client = 0 #zero for jtag
        input_cmd = sdm_cmd
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        timeout = 60
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout = 240
        resp = self.jtag.packet_send_cmd(32, header, *arg, timeout=timeout)
        self.jtag_send_noop()
        self.jtag_send_sync()
        self.jtag.unclaim_services(service="packet")
        return resp

    '''
    Modify  : self, sends the certificate via jtag
              This command will not process the certificate status. It will check the error code of the sdm cmd only.
    Input   : test_program -- True for virtual write, False otherwise
              cert_data -- The ccert data to be programmed
              skip_check -- skip checking for efuse_write_disable fuse
              ast -- whether assertion is enabled
              reserve -- values to put onto the reserve bits, must be within [0, 2^31] <- now there are 31 bits (b30:0). This could change in the future. set as 0
              success -- Checks if the command is successful or not, True if the command should respond with no error code, False if command should respond with error code
    Output  : local_respond -- the respond packet of the sdm command
    '''
    def jtag_send_certificate(self, cert_data, test_program = 1, reserve=0, success=True, skip_check=False, ast=1):
        cv_logger.info("CERTIFICATE")
        flag = 0
        sdm_version = os.getenv('DUT_SDM_VERSION')
        
        # certificate header in sdm 1.5 no longer have test mode field, remain 0 for this bit in header
        if sdm_version == "1.5":
            pass
        else:    
            if test_program:
                flag = flag | (1 << 31)
            elif not skip_check:
                if not self._fuse_write_disabled == True:
                    assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE not called before attempting real jtag_send_certificate, failing test to prevent permanently altering the device")

        if reserve > pow(2,31) or reserve < 0:
            assert_err(0, "ERROR :: Invalid reserve bit value %s" %reserve)
        else:
            flag = flag | ( reserve << 0)

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['CERTIFICATE'], flag, *cert_data)
            
        cv_logger.info("CERTIFICATE sent with flag %s (%s), with return packet of %s (%s)" %(flag, get_hex(flag), local_respond, get_hex(local_respond)))

        error_code = local_respond[0] & 0x7FF

        if (error_code == 0) and (not success): #success is false, we expect error_code != 0
            assert_err(not ast, "ERROR :: No error respond by CERTIFICATE, but test indicated it should have failed")
        elif (error_code != 0) and success:
            assert_err(not ast, "ERROR :: Unexpected given respond error code %d (%s), expected 0" %(error_code, get_hex(error_code)))

        return local_respond

    '''
    Modify  :   self, send user security option by sdm cmd
    Input   :   security_option_key -- input of security option field(list or string). See SECURITY_OPTION dict
            :   test_program -- True for virtual write, False otherwise
                ast -- Whether assertion is enabled
    Output  :   local_respond -- the respond packet of the sdm command
    '''
    def efuse_user_security_option_program(self, security_option_key, success=True, test_program=True,ast=1):
        cv_logger.info("EFUSE_USER_SECURITY_OPTION_PROGRAM")
        flag = 0
        if test_program:
            flag = flag | (1 << 31)
        elif not self._fuse_write_disabled==True:
            assert_err(0, "ERROR :: EFUSE_WRITE_DISABLE not called before attempting real EFUSE_USER_SECURITY_OPTION_PROGRAM, failing test to prevent permanently altering the device")

        cv_logger.info("Setting bit flag for security option key input : %s" %security_option_key)

        security_option_value = calculate_security_option_value(security_option_key=security_option_key)

        flag = flag | security_option_value

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['EFUSE_USER_SECURITY_OPTION_PROGRAM'], flag)
        cv_logger.info("SECURITY OPTION sent with flag %s (%s), with return packet of %s (%s)" %(flag, get_hex(flag), local_respond, get_hex(local_respond)))

        error_code = local_respond[0] & 0x7FF
        if success and (error_code!=0):
            assert_err(not ast, "ERROR :: Unexpected error respond by EFUSE_USER_SECURITY_OPTION_PROGRAM : error code return %s" %(get_hex(error_code)))
        elif (not success) and (error_code == 0):
            assert_err(not ast, "ERROR :: No error respond by EFUSE_USER_SECURITY_OPTION_PROGRAM, but test indicated it should have failed")

        return local_respond


    '''
    Modify  : self, sends NOOP command via JTAG
    Note    : this command does nothing, it always sends an OK status response.
    '''
    def jtag_send_noop(self, success=1):
        cv_logger.info("Send NOOP")
        local_respond = [None]
        try:
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['NOOP'])
            cv_logger.info("Send NOOP :: Response %s (%s)" % (str(local_respond), get_hex(local_respond)))
            
        except Exception as e:
            if success:
                assert_err(0, "ERROR :: NOOP command failed")
            else:
                cv_logger.info("NOOP Command failed as EXPECTED")

            return local_respond

        if local_respond[0] != 0 or local_respond[0] == None:
            if success:
                assert_err(local_respond[0] == 0, "ERROR :: NOOP reponse is not [0]!")
            else:
                cv_logger.info("NOOP Command failed as EXPECTED")

        else:
            if not success:
                assert_err(local_respond[0] != 0, "ERROR :: The error code is 0, expected non-zero")
            else:
                cv_logger.info("NOOP Command passed as EXPECTED")

        return local_respond


    '''
    Modify  : self, sends SYNC command via JTAG
    Note    : this command does nothing, it always sends an OK status response. Part of flush procedure
    '''
    def jtag_send_sync(self, *arg):
        cv_logger.info("Send sdm cmd SYNC")
        input_length = len(arg)
        input_id = 0 #does not matter
        input_client = 0xF #This command is the only command sent through client 0xF so clients can use it as part of discarding unwanted responses from within the data stream.
        input_cmd = SDM_CMD['SYNC']
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        timeout = 60
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout = 240
        try:
            local_respond = self.jtag.packet_send_cmd(32, header, *arg, timeout=timeout)
            self.jtag.unclaim_services(service="packet")
            cv_logger.info("Send SYNC :: Response %s (%s)" % (str(local_respond), get_hex(local_respond)))
        except:
            assert_err(0, "ERROR :: SYNC command failed")

        return local_respond

    '''
    Modify  : self, sends RSU_GET_SUBPARTITION_TABLE command via JTAG
    Note    : this command is to read sptab offset
    '''
    def jtag_read_sptab(self):
        cv_logger.info("Read SPTAB")
        try:
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['RSU_GET_SUBPARTITION_TABLE'])
        except:
            assert_err(0, "ERROR :: RSU_GET_SUBPARTITION_TABLE command failed")
        cv_logger.info("Send RSU_GET_SUBPARTITION_TABLE :: Response " + str(local_respond))
        return local_respond

    '''
    Modify  : self, sends VOLATILE_AES_WRITE command via JTAG
    Input   : key -- input qek file
              success -- True if write should success, False otherwise
    Note    : this command sets up the volatile key which is stored in battery backed RAM
    '''
    def jtag_volatile_aes_write(self, keys, success=True):
        cv_logger.info("sends VOLATILE_AES_WRITE command via JTAG")

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['VOLATILE_AES_WRITE'], *keys)
        cv_logger.info("Send VOLATILE_AES_WRITE :: Response " + str(local_respond))

        if success and local_respond != [0x0]:
            print_err("ERROR :: VOLATILE_AES_WRITE response is not [0]!")
        elif (not success) and (local_respond == [0x0]):
            print_err("ERROR :: No error respond by VOLATILE_AES_WRITE, but test indicated it should have failed")

        return local_respond

    '''
    Modify  : self, sends VOLATILE_AES_ERASE command via JTAG
    Note    : this command clears the volatile key from battery backed RAM (BBRAM)
    '''
    def jtag_volatile_aes_erase(self):
        cv_logger.info("sends VOLATILE_AES_ERASE command via JTAG")
        try:
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['VOLATILE_AES_ERASE'])
            cv_logger.info("Send VOLATILE_AES_ERASE :: Response " + str(local_respond))
            assert_err( (local_respond[0] == 0) or (local_respond[0] == 1023), "ERROR :: VOLATILE_AES_ERASE response is not [0]!")
        except:
            assert_err(0, "ERROR :: VOLATILE_AES_ERASE command failed")

        return local_respond

    '''
    Modify  : self, sends GET_CONFIGURATION_TIME command via JTAG
    Note    : this command returns the configuration time cycle count, the returned value is then converted to time in msec
    '''
    def jtag_get_configuration_time(self):
        cv_logger.info("sends GET_CONFIGURATION_TIME command via JTAG")
        try:
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['GET_CONFIGURATION_TIME'])
            cv_logger.info("Send GET_CONFIGURATION_TIME :: Response " + str(local_respond))
            assert_err(local_respond[0] == 0x2000, "ERROR :: GET_CONFIGURATION_TIME response is not [0]!")
        except:
            assert_err(0, "ERROR :: GET_CONFIGURATION_TIME command failed")

        cv_logger.info("local_respond[1] = %d"%int(local_respond[1]))
        cv_logger.info("local_respond[2] = %d"%int(local_respond[2]))

        # Return the SDM command response
        return local_respond

    '''
    Modify  : self, sends RSU_SWITCH_IMAGE command via JTAG
    Note    : this command is to switch RSU image
    '''
    def rsu_switch_image(self, address):
        cv_logger.info("Update RSU to 0x%x "%address)
        address_high = (address >> 32) & 0xffffffff
        address_low = address & 0xffffffff
        try:
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['RSU_SWITCH_IMAGE'], address_low, address_high)
        except:
            assert_err(0, "ERROR :: RSU_SWITCH_IMAGE command failed")
        cv_logger.info("Send RSU_SWITCH_IMAGE :: Response " + str(local_respond))
        assert_err(local_respond[0] == 0, "ERROR :: RSU_SWITCH_IMAGE response is not [0]!")
        qspi = self.dut.get_connector("qspi")
        if qspi != None :
            qspi.config_inactive()
        # response = self.jtag.packet_send_cmd(32, SDM_CMD['RSU_SWITCH'] | (2 << 12), address_high, address_low)
        # return response

    '''
    Require : temp must be a float or int within inclusive range of [-8388608, 8388607]
    Modify  : self, sends INTERNAL_FORCE_TEMPERATURE command via JTAG
    Input   : channel -- channel of temperature sensor to do the forcing
              temp -- temperature to be forced, in Celcius. If None, then the channel
                      will use actual temperature. Default is None
    Output  : temp give in 32bit, 2s complement, with 8bit decimal points
    '''
    def force_temperature(self, channel=0, temp=None):
        cv_logger.info(" Sending INTERNAL_FORCE_TEMPERATURE to channel %s for %s deg C" %(channel, temp))
        cv_logger.warning("This should only work on test firmware")
        temp_32bit_2complement_8bitdec = 0
        if temp == None:
            temp_32bit_2complement_8bitdec = 0x80000000
        else:
            if temp < 0:
                integer_temp = int(temp // -1)
                remind_temp = temp % 1
                if remind_temp > 0:
                    integer_temp = integer_temp + 1
                temp_32bit_2complement_8bitdec = int((((~integer_temp + 1) & 0xFFFFFF) + remind_temp)*(2**8))
            else:
                temp_32bit_2complement_8bitdec = int(temp*(2**8)) & 0xFFFFFFFF

        cv_logger.info("32bit 2s complement, 8bit decimal place temperature value is %s" %(hex(temp_32bit_2complement_8bitdec)))

        local_respond = self.jtag_send_sdmcmd(SDM_CMD['INTERNAL_FORCE_TEMPERATURE'], channel, temp_32bit_2complement_8bitdec)
        cv_logger.info("Response for INTERNAL_FORCE_TEMPERATURE %s" %local_respond)

        return temp_32bit_2complement_8bitdec

    '''
    Require : config_jtag should be called beforehand
    Input   : file_path -- path for the bitstream file (usually rbf file)
    Optional: success -- 1 if sending should success, 0 otherwise
              exp_err -- expected error message from framework if success = 0
                         if the acquired error message contains exp_err, then it is handled
              timeout -- timeout for sending bistream. default 60s
    Modify  : self, sends the bitstream via JTAG
    '''
    def send_jtag(self, file_path, success=1, exp_err=None, timeout=60, use_pgm=False, skip_extract=0):
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout = (4800 if success else 2000)
            cv_logger.info("Auto change timeout %ss" % (timeout))
        if ((success == 1) and (skip_extract==0)):
            conf_done = extract_pin_table(file_path=file_path, pin_name="CONF_DONE")
            if conf_done != None :
                self.config_done = self.dut.get_connector(conf_done,self._DEVICE_IDX)
                self._CONFIG_DONE = conf_done
        cv_logger.info("C%d :: Sending Bitstream Via JTAG" %(self._config_counter))
        self._config_counter = self._config_counter + 1
        try:
            if (os.environ.get("FWVAL_PLATFORM") == 'emulator'):
                file = open(file_path, "rb")
                if(not file):
                    print_err("ERROR :: Failed to Open the file %s" %file)
                    raise IOError
                else:
                    cv_logger.info("Opening file ==> %s successfully to read the bitstream content" %file_path )
                    bitstream_buffer = bytearray(file.read())
                    bitstream_buffer_size = len(bitstream_buffer)
                    if((bitstream_buffer_size == 0) or (success == 0)):
                        self.jtag.send_data_file(file_path, timeout=timeout)
                    else:
                        self.jtag.send_data(bitstream_buffer, timeout=timeout)

                    wait_time = 130
                    cv_logger.info("Wait for %ds" % wait_time)
                    delay(wait_time*1000)
            else:
                self.jtag.send_data_file(file_path, timeout=timeout, use_pgm=use_pgm)
        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION ::%s" %local_respond)
            if success:
                print_err("ERROR :: Failed to load bitstream UNEXPECTEDLY")
                raise e
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, local_respond)):
                    cv_logger.info("Failed to load the bitstream as EXPECTED")
                else:
                    if os.environ.get("PYCV_PLATFORM") == 'simics' :
                        # For now it is ok to allow different Error (as long as it is still an error)
                        # Simics is not SysCon anyway, will unify the error after this
                        print("Simics Warning :: Expected error is \"%s\", but found \"%s\"" % (exp_err, local_respond))
                    else :
                        print_err("ERROR :: Failed to load bitstream, but different error as expected. Expect:%s. Measured:%s" % (exp_err, local_respond))
                        raise e
        else:   #if no error
            if success:
                cv_logger.info("Successfully loaded bitstream as expected")
            else:
                #don't to assert_err, that will cause the reg.rout to be edited, which may not be what we want
                assert False, "WARNING ::  Successfully loaded bitstream when failure expected, check PINS and STATUS to see if configuration is done"

    '''
    This function is used for pr_bad cases : pr_jtag_bad when it doesn't matter whether the PR goes through JTAG successfully
    Require : config_jtag should be called beforehand
    Input   : file_path -- path for the bitstream file (usually rbf file)
    Optional: success -- 1 if sending should success, 0 otherwise
              exp_err -- expected error message from framework if success = 0
                         if the acquired error message contains exp_err, then it is handled
              timeout -- timeout for sending bistream. default 60s
    Modify  : self, sends the bitstream via JTAG
    '''
    def send_pr_jtag_bad(self, file_path, exp_err=None, timeout=60):
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout = timeout * 300
        cv_logger.info("C%d :: Sending Bitstream Via JTAG" %(self._config_counter))
        self._config_counter = self._config_counter + 1
        try:
            self.jtag.send_data_file(file_path, timeout=timeout)
        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION ::%s" %local_respond)

            if(re.search(exp_err, local_respond)):
                cv_logger.info("Failed to load the PR bitstream as EXPECTED")
            else:
                if os.environ.get("PYCV_PLATFORM") == 'simics' :
                    # For now it is ok to allow different Error (as long as it is still an error)
                    # Simics is not SysCon anyway, will unify the error after this
                    print("Simics Warning :: Expected error is \"%s\", but found \"%s\"" % (exp_err, local_respond))
                else :
                    print_err("ERROR :: Failed to load bitstream, but different error as expected")
                    raise e
        else:   #if no error

            cv_logger.info("Successfully loaded the PR bitstream as expected")


    '''
    Require : expected status and pins should be up to date before calling
              this method
    Input   : file_path -- path for the bitstream file (usually rbf file)
              success -- 1 if sending should success, 0 otherwise
              skip -- 1 if want to skip the pin and status check BEFORE THE CONFIGURATION
                      useful if do back to back complete_config (won't verify two times)
              skip_after -- like skip, but for skipping the checks after attempted configuration
              skip_ver -- skip version check of the firmware
              retain -- 1 if the current configuration should be retained after
                        failed attempted configuration
              before_cmf_state -- whether the device is in cmf state (currently, before config)
              failed_cmf_state -- whther the device is in cmf_state after EXPECTED
                FAILED configuration. Device must currently be in bootrom stage for this to happen
                and the cmf must not be loaded at the attempted configuration
              failed_state -- specific failed configuration state to match when configuration failed.
                Check only when success is 0,
                if not specified (default to 1), test just make sure state in CONFIG_STATUS returns non-zero.
              ast -- 0 if assertion disabled for status and pin check
              exp_err -- string of expected error message when configuration fails (just part of it is fine
              timeout -- timeout for sending bistream, default 60s
              send_noop_sync -- [True]send NOOP and SYNC command before do config.  the noop and sync is set as default in configuration , as that is the requirement to do so.
                                For program ccert and qky, it is not recquire to send noop and sync.
                                NOOP is used to clear the command buffer and SYNC were used to check device responsive or not.
              test_mode -- UDS test mode
    Modify  : self, sends jtag_config, then sends the bitstream via JTAG
              checks all results before and after configuration
    Output  : a list of True and False for pin and status checks
    Note    : nconfig and nstatus are constant throughout this method
    '''
    def complete_jtag_config(self, file_path, before_cmf_state, timeout=60, skip=0, skip_after=0,skip_ver=0, failed_cmf_state=1, success=1, failed_state=1, retain=0, ast=0, exp_err=None,index="",send_efuse_write_disable=1, use_pgm=False, skip_extract=0, send_noop_sync=True, skip_ewd=0, test_mode=None):
        cv_logger.info("Run jtag configuration with %s" %file_path)
        local_success = []
        #check pins and config_status if not skipped
        if not skip:
            cv_logger.info("Checking pin and status before configuration")
            local_success.append(self.verify_pin(ast=ast,index=index))
            local_success.append(self.verify_status(cmf_state=before_cmf_state, ast=ast,skip_ver=skip_ver))

        if send_noop_sync:
            #send NOOP cmd
            self.jtag_send_noop()
            #send jtag sync
            dummy_data = 0x0000ABCD
            self.jtag_send_sync(dummy_data)

        #send bitstream via jtag
        self.config_jtag()
        try:
            self.send_jtag(file_path=file_path, success=abs(success), exp_err=exp_err, timeout=timeout, use_pgm=use_pgm, skip_extract=skip_extract)
        except Exception as e:
            self._lib_delay()
            if success:
                cv_logger.info("Printing pin and status after unexpected configuration result")
                cv_logger.info("Please ignore the expected values here (not updated since configuration result unexpected)")
                self.verify_pin(ast=0,index=index)
                self.verify_status(cmf_state=2, ast=0,skip_ver=skip_ver)
                raise e
            else:
                cv_logger.info("Bitstream finished sending via JTAG although expected failure, check pin and status to verify if configuration is successful.")

        self._lib_delay()

        if not skip_after:
            cv_logger.info("Checking pin and status after attempted JTAG configuration")
            if success:
                #update expectations
                self.update_exp(state=0x0, config_done=1, init_done=1, avst_ready=0)
                #check pins and config_status
                local_success.append(self.verify_pin(ast=ast,index=index))
                local_success.append(self.verify_status(cmf_state=1, ast=ast,skip_ver=skip_ver))
            else:
                #update expectations if not retain
                if not retain:
                    self.update_exp(state=failed_state, config_done=0, init_done=0)
                #check pins and config_status
                local_success.append(self.verify_pin(ast=ast,index=index))
                local_success.append(self.verify_status(cmf_state=failed_cmf_state, ast=ast,skip_ver=skip_ver))
        else:
            cv_logger.warning("Skipped checking after configuration")
        # Send efuse_write_disable command again after reconfiguration to make sure the sdm command is set
        if (self._fuse_write_disabled) and (send_efuse_write_disable):
            if skip_ewd:
                cv_logger.info("Skip calling EFUSE_WRITE_DISABLE command again after reconfiguration")
            else:
                cv_logger.info("Send EFUSE_WRITE_DISABLE command again after reconfiguration to make sure it is SET")
                self.efuse_write_disable(skip_program=False,test_mode=test_mode)

        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            wait_time = 130
            cv_logger.info("Wait for %ds" % wait_time)
            delay(wait_time*1000)

        cv_logger.info("Finished complete_jtag_config")
        return local_success

    '''
    Require : expected status and pins should be up to date before calling
              this method
    Input   : file_path -- path for the bitstream file (usually rbf file)
              success -- 1 if sending should success, 0 otherwise
              failed_cmf_state -- whether the device is in cmf_state after EXPECTED
                FAILED configuration. Device must currently be in bootrom stage for this to happen
                and the cmf must not be loaded at the attempted configuration
              ast -- 0 if assertion disabled for status and pin check
              exp_err -- string of expected error message when configuration fails (just part of it is fine
              timeout -- timeout for sending bistream, default 60s
              cancel -- 1 if cancel enabled 0 and update the reconfig_status. if cancel disabled for usual reconfig_status
    Modify  : self, sends jtag_reconfig, then sends the bitstream via JTAG
              checks all results before and after configuration
    Output  : a list of True and False for pin and status checks
    Note    : nconfig and nstatus are constant throughout this method
    '''
    def pr_jtag_config(self, file_path, success=1, timeout=60, ast=0, exp_err=None, cancel=0,index="", send_efuse_write_disable=1):
        cv_logger.info("Run partial configuration thru jtag with %s" %file_path)
        local_success = []

        self.reconfig_jtag()

        #Do PR
        try:
            self.send_jtag(file_path=file_path, success=success, exp_err=exp_err, timeout=timeout)
        except Exception as e:
            if(success):
                self._lib_delay()
                cv_logger.info("Printing pin and status after unexpected PR result")
                cv_logger.info("Please ignore the expected values here (not updated since PR result unexpected)")
                self.verify_pin(ast=0,index=index)
                self.verify_status(cmf_state=2, ast=0)
                self.verify_status(cmf_state=1, pr=1, ast=0)
                raise e
            else:
                #assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                cv_logger.info("PR bitstream Failed to load as EXPECTED")

        self._lib_delay()

        cv_logger.info("Checking pin and status after attempted JTAG PR")
        #update expectations for CONFIG_STATUS; should remains passed after perform PR
        # self.update_exp(state=0x0, config_done=1, init_done=1, avst_ready=0)
        self.update_exp(state=0x0)

        #check pins and config_status
        local_success.append(self.verify_pin(ast=ast,index=index))
        local_success.append(self.verify_status(cmf_state=1, ast=ast))

        # update expectations for RECONFIG_STATUS
        if success:
            self.update_exp(state=0)

        else:
            self.update_exp(state=1)

        if (cancel == 0):
            cv_logger.info("Check reconfig_status")
            if (success == 1):
                cv_logger.info("Verify reconfig status for PR SUCCESS case")
                local_success.append(self.verify_status(cmf_state=1, pr=1, ast=ast))
            else:
                cv_logger.info("Verify reconfig status for PR BAD case")
                local_success.append(self.verify_status(cmf_state=1, pr=1, ast=ast, pr_bad=1))
        else:
            cv_logger.info("Skip check for reconfig_status for cancel testcase")
        cv_logger.info("Finished pr_jtag_config")

        # Send efuse_write_disable command again after reconfiguration to make sure the sdm command is set
        if (self._fuse_write_disabled) and (send_efuse_write_disable):
            cv_logger.info("Send EFUSE_WRITE_DISABLE command again after reconfiguration to make sure it is SET")
            self.efuse_write_disable(skip_program=False)

        return local_success

    def pr_jtag_fail(self, file_path, success=0, skip=0, timeout=60, ast=0, exp_err=None,index="", send_efuse_write_disable=1):
        cv_logger.info("Run partial configuration thru jtag with %s" %file_path)
        local_success = []

        self.reconfig_jtag()

        #Do PR
        try:
            self.send_jtag(file_path=file_path, success=success, exp_err=exp_err, timeout=timeout)
        except Exception as e:
            self._lib_delay()
            cv_logger.info("Printing pin and status after unexpected PR result")
            cv_logger.info("Please ignore the expected values here (not updated since PR result unexpected)")
            self.verify_pin(ast=0,index=index)
            self.verify_status(cmf_state=2, ast=0)
            self.verify_status(cmf_state=1, pr=1, ast=0)
            raise e

        self._lib_delay()

        cv_logger.info("Checking pin and status after attempted JTAG PR")

        #check pins and config_status
        local_success.append(self.verify_pin(ast=ast,index=index))
        local_success.append(self.verify_status(cmf_state=1, ast=ast))

        # update expectations for RECONFIG_STATUS
        if success:
            self.update_exp(state=0)
        else:
            self.update_exp(state=1)
        local_success.append(self.verify_status(cmf_state=1, pr=1, ast=ast))

        cv_logger.info("Finished pr_jtag_success")

        # Send efuse_write_disable command again after reconfiguration to make sure the sdm command is set
        if (self._fuse_write_disabled) and (send_efuse_write_disable):
            cv_logger.info("Send EFUSE_WRITE_DISABLE command again after reconfiguration to make sure it is SET")
            self.efuse_write_disable(skip_program=False)
        return local_success

    '''
    private function, do not call in main()
    Checks the loaded issp properties
    Input: issp property for the design in the device (input_design_prop), and the expected design (output_design_prop)
    '''
    def _gen_verdict_desgnspec(self, input_design_prop, output_design_prop):
        if(input_design_prop['source_width'] != output_design_prop['source_width']):
            cv_logger.error("Design Input Source Width Mismatched <> EXPECTED = 0x%x and MEASURED = 0x%x" %(input_design_prop['source_width'],output_design_prop['source_width']))
            assert_err(0, "ERROR :: LOADED design property incorrect")

        if(input_design_prop['probe_width'] != output_design_prop['probe_width']):
            cv_logger.error("Design Output Probe Width Mismatched <> EXPECTED = 0x%x and MEASURED = 0x%x" %(input_design_prop['probe_width'],output_design_prop['probe_width']))
            assert_err( 0, "ERROR :: LOADED design property incorrect")

        cv_logger.info("PASS :: Design properties Matched EXPECTED_SOURCE_WIDTH = 0x%x and MEASURED_SOURCE_WIDTH = 0x%x" %(input_design_prop['source_width'], output_design_prop['source_width']))
        cv_logger.info("PASS :: Design properties Matched EXPECTED_PROBE_WIDTH  = 0x%x and MEASURED_PROBE_WIDTH  = 0x%x" %(input_design_prop['probe_width'], output_design_prop['probe_width']))
        cv_logger.info("")


    '''
    private function, do not call in main()
    Checks the loaded design logic via issp
    Input: handler for system console (syscon_handle), input for the source (input_list), output for the probe (output_list)
    '''
    def _gen_verdict_function(self, syscon_handle, input_list, output_list):
        local_condition_pass    = True

        for index in range(0,len(input_list)):

            'writing the Source Data to the Design'
            syscon_handle.issp_write_ip(input_list[index])
            local_input_value   = syscon_handle.issp_read_ip()
            local_measured_op   = syscon_handle.issp_read_op()
            if(local_input_value != input_list[index]):
                print_err("ERROR :: Failed to write Input Source = 0x%x" %input_list[index])
                local_condition_pass = False
            elif(local_measured_op != output_list[index]):
                print_err("ERROR :: OutPut Value of the Design Mismatched <> EXPECTED = 0x%x and MEASURED = 0x%x" %(output_list[index], local_measured_op))
                local_condition_pass = False
            else:
                cv_logger.info("PASS :: Input to Design = 0x%x; Expected OP = 0x%x  and Measured OP = 0x%x" %(local_input_value, output_list[index], local_measured_op))

        assert_err(local_condition_pass, "ERROR :: Design logic incorrect")




    '''
    **********************************************************************************************
    Method :: This is the place holder to plug CRAM/ERAM DUMP PROCEDURE
    **********************************************************************************************
    '''
    # def stop_emulator_get_dumps(self, emu_sector_dump_filename, emu_eram_sector_dump_filename):
        # s = create_emu_command_connection()
        # try:
            # expected_reply = 'emu_hello'
            # reply = s.recv(len(expected_reply))
            # cv_logger.info("_EMU :: %s" %reply)
            # assert reply == expected_reply, reply

            # # send command to run 200ms
            # emu_command_run_100ms(s)
            # emu_command_run_100ms(s)

            # # send command to start sector backdoor dump
            # emu_command_do_sector_dump(s, "cram")
            # emu_command_do_sector_dump(s, "eram")


            # # send command to retrieve the dump file
            # emu_command_get_sector_dump(s, emu_sector_dump_filename, "cram")
            # emu_command_get_sector_dump(s, emu_eram_sector_dump_filename, "eram")

            # s.send('emu_bye\n')

        # except socket.timeout:
            # cv_logger.info("_EMU :: timeout")
            # pass
        # s.close()

    def emu_CRAMERAM_DUMP(self, design_name):

        cv_logger.debug("PLACE HOLDER TO CALL EMULATOR CRAM ERAM DUMP LOGIC......................")
        # cv_logger.debug("START CRAM DUMP LOGIC......................")
        # emu_eram_sector_dump_filename = 'memory_postdump.tar.gz'
        # emu_sector_dump_filename = 'emu_sector_dump.tar.gz'
        # eram_sector_dump_dir = 'memory_postdump'
        # sector_dump_dir = 'sector_dumps'
        # golden_dir = "golden_" + design_name + "/1"

        # self.stop_emulator_get_dumps(emu_sector_dump_filename, emu_eram_sector_dump_filename)

        # # Extract CRAM dump
        # assert os.path.exists(emu_sector_dump_filename)
        # if not os.path.exists(sector_dump_dir):
            # os.mkdir(sector_dump_dir)
        # subprocess.check_call(['tar', '-xzf', emu_sector_dump_filename, '--directory', sector_dump_dir])

        # # extract eram dumps
        # assert os.path.exists(emu_eram_sector_dump_filename)
        # if not os.path.exists(eram_sector_dump_dir):
            # os.mkdir(eram_sector_dump_dir)
        # subprocess.check_call(['tar', '-xzf', emu_eram_sector_dump_filename, '--directory', eram_sector_dump_dir])

        # # build cram collector
        # subprocess.check_call(['gmake', '-f', 'cram_collector.gmake'])
        # subprocess.check_call(['gmake', '-f', 'eram_collector.gmake'])

        # # Must have golden directory before proceed to comparison
        # print golden_dir
        # subprocess.check_call(['pwd'])
        # assert os.path.exists(golden_dir)

        # compare_fail_count = cram_collector_compare_all('./cram_collector_fm.exe', golden_dir, sector_dump_dir, os.environ.get("REGTEST_REPOSITORY")+"regtest/quartus/devices/firmware/nd/s10/integration_test/util/phantom/fm6", '0,22')

        # # wait_until_emulator_stop()
        # # Generate shell comparison script
        # string = "python generate_myrun.py --golden_dir " + golden_dir + " > myrun.sh"
        # subprocess.check_call(string, shell=True)

        # # Call comparison script. It will compare all sectors eram dump files
        # cmd = ['sh','myrun.sh']
        # subprocess.call(cmd)

        # TOTAL_Y_COLUMNS = 5
        # TOTAL_X_COLUMNS = 6

        # success_count = 0
        # failure_count = 0

        # for y in range(0,TOTAL_Y_COLUMNS):
          # for x in range(0,TOTAL_X_COLUMNS):
            # folderName = "x" + str(x) + "y" + str(y)
            # if os.path.exists("run/" + folderName):
              # for file in os.listdir("run/" + folderName):
                # if file.endswith("FAILED"):
                  # cv_logger.info("FAILED")
                  # failure_count = failure_count +1
                # elif file.endswith("SUCCESS"):
                  # cv_logger.info("SUCCESS")
                  # success_count = success_count +1

        # cv_logger.info("success_count = %d" % success_count)


        # assert compare_fail_count == 0, "CRAM comparison fail!"
        # assert failure_count  == 0, "ERAM comparison fail!"

    '''
    Dump SDM trace
    Require : use on emulator platform only. Trigger emulator to start dumping
              sdm_instr.vhex, sdm_ctrl.vhex sdm_nios.tr
    Input   : None
    Output  : sdm_instr.vhex, sdm_ctrl.vhex sdm_nios.tr in folsom
    Note    : to convert them to human readable format. follow these steps
                . Goto folsom result dir, look for sdm_instr.vhex and sdm_ctrl.vhex
                . $ python /nfs/site/disks/fm8_emu_1/users/kahwaile/fm8_model_bringup/nios_trace_from_hex.py sdm_instr.vhex sdm_ctrl.vhex sdm_nios.tr
                . Copy sdm_nios.tr back to pice
                . Extract the <devicefamily>_*extras.zip <dev>/SHA_384/cmf_nsp.elf
                . $ arc shell python/3.7.3 quartuskit
                . $ export PYTHONPATH=/p/psg/swip/w/kahwaile/qshell/default-sc/acds/main/regtest/quartus/devices/firmware/nd/testcases/aibssm/util/lib/python3.6:$PYTHONPATH
                . $ python -m cnt.tools.nios2-trace-parallel sdm_nios.tr -o sdm_nios.decoded -p 32 --elf=cmf_nsp.elf
                Reference: https://wiki.ith.intel.com/display/PSWEFW/CvP+Emulator+BKM#CvPEmulatorBKM-Decodingcpu.trfile:

              OR

              /p/psg/swip/w/checlim/tools/fw-tools/convert_nios_tr.sh cmf_main.elf sdm_nios.tr sdm_nios_tr_cmf.txt
    '''
    def dump_trace(self):
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            signal_emulator_dump_trace()

    '''
    Fetch SDM gtrace for emulator jobs and print the gtrace
    Require : use on emulator platform only. Trigger emulator to start gtrace retrieval
    Input   : None
    Output  : gtrace printout on stdout
    '''
    def get_gtrace_dump(self):
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            emu_command_get_gtrace()

    '''
    Input    : design_name -- as long as design_name contains "and"/"or" (case insensitive), this function will verify whether
               the programmed device has the correct design
               dut_closed -- True if dut is closed, False otherwise
    '''
    def verify_design(self, design_name, dut_closed=True):

        '-------------------------ADDING LOGIC TO SWITCH BETWEEN EMULATOR OR REAL SILICON VERIFICATION------------------'
        if os.environ.get("PYCV_PLATFORM") == 'simics' :

            cv_logger.warning("Simics skip verifying design ...")

        elif(os.environ.get("FWVAL_PLATFORM") == 'emulator'):

            self.emu_CRAMERAM_DUMP(design_name)

        else:
            cv_logger.info("V%d :: Verify Design: %s" %(self._verify_counter, design_name))
            self._verify_counter = self._verify_counter + 1
            design_name = design_name.lower()

            if(re.search("and", design_name) != None):
                design = "AND_GATE"
            elif(re.search("or", design_name) != None):
                design = "OR_GATE"
            else:
                assert_err(0, "ERROR :: Design name does not have 'and' or 'or'")

            cv_logger.info("The design is expected to have %s functionality" %design)


            if not dut_closed:
                cv_logger.info("DUT is not closed, need to close JTAG connector and platform")
                self.dut.connectors["jtag"].close()
                self.dut.connectors.pop("jtag")
                self.jtag = None
                self.dut.close_platform()
                delay(3000)


            kill_all_syscon()

            #system-console list before verifying design
            pids_before = find_syscon()

            #start a system-console
            local_syscon    = startscon()
            local_syscon.handle_system_console()

            #check issp
            local_syscon.issp_info(self.issp_prop)

            #check issp properties
            self._gen_verdict_desgnspec(self.issp_prop, ISSP_ARGS[design]['PROP'])

            #check functionality via input and probes
            self._gen_verdict_function(local_syscon, ISSP_ARGS[design]['INPUT'], ISSP_ARGS[design]['OUTPUT'])

            #close the service path
            local_syscon.close_issp_path()

            #close the system console
            local_syscon.kill_system_console()

            #system-console list after verifying design
            pids_after = find_syscon()

            #get difference, this is a list of the new system-console process(es)
            pids_diff = list(set(pids_after) - set(pids_before))

            #kill those system-consoles
            for pid in pids_diff:
                kill_ps(pid)

            if not dut_closed:
                cv_logger.info("Reopening JTAG connector and platform...")
                i = 1
                retry = True
                with Timeout(65):
                    while retry:
                        try:
                            #pids_before = find_syscon()
                            self.dut.open_platform()
                            retry = False
                        except:
                            i = i + 1
                            #pids_after = find_syscon()
                            #pids_diff = pids_diff + list(set(pids_after) - set(pids_before))
                cv_logger.info("Reopened platform after %d tries" %i)
                self.jtag = self.dut.get_connector("jtag")
                assert_err(self.jtag != None, "ERROR :: Cannot reopen the JTAG Connector")
                self.dut.send_system_console("refresh_connections", print_console=3)

            cv_logger.info("Design verification completed")

    '''
    Input    : syscon -- system console script to run
               syscon_arg -- argument to run with system console
    '''
    def pr_fpga_syscon(self, syscon, syscon_arg,sof_path=None, ast=0, success=1, exp_err=None):
        cv_logger.info("PR thru FPGA with system-console using %s, run with %s" %(syscon, syscon_arg))
        local_pass = True
        try:
            run_command("system-console --script=%s %s %s" % (syscon, syscon_arg, sof_path), ast=ast)
            if success != 1:
                local_pass = False
                if ast:
                    assert_err(0, "ERROR :: Expected failed in PR via FPGA, but passed!!")
                else:
                    print_err("ERROR :: Expected failed in PR via FPGA, but passed!!")
        except Exception as e:

            err_msg = str(e)
            if success:
                local_pass = False

                #log the traceback into stderr
                logging.exception('')

                if ast:
                    assert_err(0, "ERROR :: Failed to PR via FPGA")
                else:
                    print_err("ERROR :: Failed to PR via FPGA")
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, err_msg)):
                # searchObj = re.search( r'Error: PR_ERROR was triggered', err_msg, re.M|re.I)
                # if searchObj:
                    cv_logger.info("Expected failed in PR via FPGA with expected error print out")
                else:
                    local_pass = False

                    #log the traceback into stderr
                    logging.exception('')

                    if ast:
                        assert_err(0, "ERROR :: Expected failed in PR via FPGA but cannot get the expected error print out")
                    else:
                        print_err("ERROR :: Expected failed in PR via FPGA but cannot get the expected error print out")

        return local_pass

    '''
    Input    : syscon -- system console script to run
               syscon_arg -- argument to run with system console
    '''
    def verify_design_syscon(self, syscon, syscon_arg, ast=0, success=1, exp_err=None,dut_closed=False,sof_path=None):
        cv_logger.info("Verify Design with system-console using %s, run with %s %s" %(syscon, syscon_arg, sof_path))
        local_pass = True

        if dut_closed:
            cv_logger.info("DUT is closed, need to close JTAG connector and platform")
           #self.dut.connectors["jtag"].close()
           #self.dut.connectors.pop("jtag")
           #self.jtag = None
            cv_logger.info("Closing System Console Platform!!")
            self.dut.close_platform()
            delay(3000)

        #system-console list after verifying design
        pids_before = find_syscon()

        try:
            run_command("system-console --script=%s %s %s" % (syscon, syscon_arg, sof_path))
            if success != 1:
                local_pass = False
                if ast:
                    assert_err(0, "ERROR :: Expected failed in verify design, but passed!!")
                else:
                    print_err("ERROR :: Expected failed in verify design, but passed!!")
        except Exception as e:

            err_msg = str(e)
            if success:
                local_pass = False

                #log the traceback into stderr
                logging.exception('')

                if ast:
                    assert_err(0, "ERROR :: Failed to verify design")
                else:
                    print_err("ERROR :: Failed to verify design")
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, err_msg)):
                # searchObj = re.search( r'ERROR: Expected .* but read .*', err_msg, re.M|re.I)
                # if searchObj:
                    cv_logger.info("Expected failed in verify design with expected error print out")
                else:
                    local_pass = False

                    #log the traceback into stderr
                    logging.exception('')

                    if ast:
                        assert_err(0, "ERROR :: Expected failed in verify design but cannot get the expected error print out")
                    else:
                        print_err("ERROR :: Expected failed in verify design but cannot get the expected error print out")

        #system-console list after verifying design
        pids_after = find_syscon()

        #get difference, this is a list of the new system-console process(es)
        pids_diff = list(set(pids_after) - set(pids_before))

        #kill those system-consoles
        for pid in pids_diff:
            kill_ps(pid)

        if dut_closed:
            cv_logger.info("Restarting System Console Platform")
            self.dut.restart_platform()
            delay(3000)

        return local_pass

    # '''
    # EOL :: Replace with new function!! See new function below verify_design_andor
    # Input    : design_name -- as long as design_name contains "and"/"or" (case insensitive), this function will verify whether
               # the programmed device has the correct design
               # ast      -- default 1 to assert error when failed, else will return failure without assertion
    # '''
    # def verify_design_andor(self, design_name, ast=1):

        # '-------------------------ADDING LOGIC TO SWITCH BETWEEN EMULATOR OR REAL SILICON VERIFICATION------------------'
        # if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):

            # self.emu_CRAMERAM_DUMP()

        # else:
            # cv_logger.info("V%d :: Verify Design: %s" %(self._verify_counter, design_name))
            # self._verify_counter = self._verify_counter + 1
            # design_name = design_name.lower()

            # if(re.search("and", design_name) != None):
                # design = "and_gate_design"
            # elif(re.search("or", design_name) != None):
                # design = "or_gate_design"
            # else:
                # assert_err(0, "ERROR :: Design name does not have 'and' or 'or'")

            # cv_logger.info("The design is expected to have %s functionality" %design)

            # local_pass = self.verify_design_syscon(syscon="verify_design.tcl", syscon_arg=design, ast=ast)

            # cv_logger.info("Design verification completed")
            # return local_pass


    '''
    Input    : design_name -- as long as design_name contains "and"/"or" (case insensitive), this function will verify whether
               the programmed device has the correct design
               ast      -- default 1 to assert error when failed, else will return failure without assertion
    '''
    def verify_design_andor(self, design_name, ast=1, issp_tag="issp", issp_index=0, skip_crameram_dump=0): # GEN: + skip_cameraram_dump =0

        '-------------------------ADDING LOGIC TO SWITCH BETWEEN EMULATOR OR REAL SILICON VERIFICATION------------------'
        if os.environ.get("PYCV_PLATFORM") == 'simics' :

            # Maybe support Simics CRAM/ERAM dump in the future
            return True

        elif (os.environ.get("FWVAL_PLATFORM") == 'emulator') :
            dut_rev = os.environ['DUT_REV']
            return True

            if (skip_crameram_dump == 1) or (dut_rev == "DMD") or (dut_rev == "DMTC"):
                return True
            else:
                self.emu_CRAMERAM_DUMP(design_name)

        else: # Satya: Suggestion to take latest changes from jian kang implementation in testkit related to refresh connection
            cv_logger.info("\nV%d :: Verify Design: %s" %(self._verify_counter, design_name))
            if self.DUT_FAMILY == "diamondmesa" or os.environ.get("PYCV_PLATFORM") == 'simics' :
                # diamondmesa do internal BRAM_HASH_CHECK. No external check available.
                if os.environ.get("PYCV_PLATFORM") == 'simics' :
                    cv_logger.warning("Simics skip verifying design ...")
                else :
                    cv_logger.info("INFO :: Skipping verify_design..")
                local_pass = 1
                return local_pass
            cv_logger.info("\nV%d :: Verify Design: %s" %(self._verify_counter, design_name))
            cv_logger.info("V%d :: Verify Design: %s" %(self._verify_counter, design_name))
            self._verify_counter = self._verify_counter + 1
            local_pass = 1

            design_name = design_name.lower()
            if(re.search("and", design_name) != None):
                design = "and_gate_design"
            elif(re.search("or", design_name) != None):
                design = "or_gate_design"
            else:
                assert_err(0, "ERROR :: Design name does not have 'and' or 'or'")

            cv_logger.info("The design is expected to have %s functionality" %design)

            # Refresh connections
            self.jtag.send_broadcast("dut_program")

            input_data = [0b00, 0b01, 0b10, 0b11]
            expected_data = {
                'and_gate_design'   : [0, 0, 0, 1],
                'or_gate_design'    : [0, 1, 1, 1]
            }

            self.issp0 = self.dut.get_connector(issp_tag, issp_index)
            assert_err(self.issp0 != None, "ERROR :: Cannot open ISSP index 0 Connector")
            for count in range(len(input_data)):
                input = input_data[count]
                exp_output = expected_data[design][count]

                cv_logger.info("Writing source data with 0x%x" %input)
                self.issp0.write_source_data(input)

                # source_value = self.issp0.read_source_data()
                # cv_logger.info("Read source data after write_source_data is " +str(source_value))

                probe_value = self.issp0.read_probe_data()
                cv_logger.info("Read probe data after write_source_data is " +str(probe_value))

                if ( probe_value != exp_output):
                    local_pass = 0
                    if ast:
                        assert_err(0, "ERROR :: Expected value: %d Read value: %d" %(exp_output, probe_value))
                    else:
                        cv_logger.warning("Expected value: %d Read value: %d" %(exp_output, probe_value))

            self.issp0.unclaim_issp_service()
            # local_pass = self.verify_design_syscon(syscon="verify_design.tcl", syscon_arg=design, ast=ast)

            cv_logger.info("Design verification completed")
            return local_pass
    '''
    Require  : need the acdskit resource!!
    Optional : dump - default True to print out the trace content
    '''
    def collect_pgm_trace(self, dump=True, trace=None) :

        if os.environ.get("PYCV_PLATFORM") == 'simics' :
            cv_logger.warning("Simics skip collecting PGM trace ...")
        else :
            cv_logger.info("Collect trace")
            if self.jtag.packet_service != None :
                self.jtag.unclaim_services(service="packet")

            if(trace == None):
                trace = "cmf.trace"
                trace_log = "cmf.trace.out"
            else:
                trace_log = trace + ".out"
            try:
                run_command("quartus_pgm -c %d -m jtag --trace %s" % (self.dut_cable, trace))
                run_command("pgmalgo_trace_dump %s %s" % (trace, trace_log))
                if dump:
                    with open(trace_log, 'r') as fin:
                        print (fin.read())
            except:
                cv_logger.warning("Fail to collect trace, make sure you have acdskit resource")
            cv_logger.info("Done collecting trace")

    '''
    Require : Check jtagconfig --debug and look for design hash and sld node
    Output  : design hash and sld node
    '''
    def check_idle_jtagconfig(self) :
        
        # Vulture Ridge specific
        self.dut.set_jtagmux("dut")
        
        returnmsg = run_command("jtagconfig --debug")
        lines = returnmsg.split("\n")
        design_hash_return = False
        sld_node_return = False
        found_dut = 0
        dut_line = 0
        for line in lines :
            line = line.strip()
            line = line.rstrip()
            if line.find("%d) " % self.dut.dut_cable) == 0 :
                found_dut = 1
            elif len(line) and found_dut == 1 :
                if line.find("%d) " % (self.dut.dut_cable+1)) == 0 :
                    break
                else :
                    dut_line += 1
                    info = line.split()

                    if dut_line == 3 or dut_line == 4:
                        if info[0] != "Unable" and info[0] != "Captured":
                            if len(info) > 1 :
                                if info[0] == "Design" and info[1] == "hash" :
                                    design_hash_return = info[2]
                                elif info[1] == "Node" :
                                    sld_node_return = info[2]
                    if dut_line == 5:
                        if not design_hash_return or not sld_node_return:
                            design_hash_return = False
                            sld_node_return = False
                        break

        return (design_hash_return, sld_node_return)

    '''
    *********************************************************************************************
    Input   : bitstream --  bytearray of the bitstream read
    Output  : address extracted from bitstream
    *********************************************************************************************
    '''
    def read_add(self, bitstream, index_start, index_end):
        src_buff        = bitstream[index_start:index_end]
        src_buff_le     = reverse_arr(src_buff)
        add = int(binascii.hexlify(src_buff_le),16)
        return add

    '''
    Input   : bitstream --  bytearray of the bitstream read
              mode -- "as" for active serial, others other wise, default "as"
    Modify  : reads the bitstream given and initializes these variables:
              self.MAIN_ADD -- a list of main section addresses
              self.MAIN_SEC_NUM -- number of main sections
              self.SSBL_START_ADD -- start address of ssbl
              self.SSBL_END_ADD -- last address of ssbl
              self.TRAMPOLINE_START_ADD -- start address of trampoline
              self.TRAMPOLINE_END_ADD -- last address of trampoline
              self.SYNC_START_ADD -- start address of sync
              self.SYNC_END_ADD -- last address of sync
              puf_enable -- enable obtention of puf addresses
                self.iid_puf_addr.PUF_OFFSET = []         #Offset location in MIP i.e. 1F90/1F98 for PUF Data
                self.iid_puf_addr.PUF_ADD = []           #Offset location for base of actual PUF data i.e. 100000/108000
                self.iid_puf_addr.HELP_DATA_OFFSET = []  #Contains the offset for the help data i.e. 100008/108008
                self.iid_puf_addr.WKEY_DATA_OFFSET = []  #Contains the offset for the wkey data i.e. 10000C/10800C
                self.iid_puf_addr.PUF_DATA_ADDR = []      #Offset location for actual PUF data i.e. 101000/109000
                self.iid_puf_addr.PUF_WKEY_ADDR = []      #Offset location for actual WKEY data i.e. 102000/110000
    '''
    def get_fw_add(self, bitstream, mode="as", puf_enable=0, a2_startaddr=0):

        index_offset    = 0
        index_size      = 1

        print("A2_address is %x" %a2_startaddr)
        cv_logger.info("Bitstream processing to get address")

        if (mode == "as"):
            # Main Image Pointer - last 256 bytes  of the second 4kB block within the firmware section
            # for each in MAIN_IMAGE_POINTER:
                # index_start     = MAIN_IMAGE_POINTER[each][index_offset]
                # index_end       = index_start + MAIN_IMAGE_POINTER[each][index_size]
                # src_buff        = bitstream[index_start:index_end]
                # src_buff_le     = reverse_arr(src_buff)
                # add = int(binascii.hexlify(src_buff_le),16)
                # cv_logger.info("Main Image Pointer %s: 0x%08x"%(each,add))

            index_start     = MAIN_IMAGE_POINTER['sec_num'][index_offset] + a2_startaddr
            index_end       = index_start + MAIN_IMAGE_POINTER['sec_num'][index_size]
            add = self.read_add(bitstream, index_start, index_end)
            cv_logger.info("Main Image Pointer MAIN_SEC_NUM: 0x%08x"% add)
            cv_logger.info("a2_startaddr: 0x%08x"% a2_startaddr)
            self.MAIN_SEC_NUM = add
            self.MAIN_ADD = []

            # dummy add 0
            self.MAIN_ADD.append(0)

            main_sec = 1
            if self.MAIN_SEC_NUM >= 1 :
                index_start     = MAIN_IMAGE_POINTER['1st_main_add'][index_offset] + a2_startaddr
                index_end       = index_start + MAIN_IMAGE_POINTER['1st_main_add'][index_size]
                add = self.read_add(bitstream, index_start, index_end)
                #assert_err ( add != 0, "ERROR :: 1st main address cannot be 0")
                # if address == 0, it means we are using relative address
                if add == 0 :
                    #For QSPI relative addressing mode, Main sections starting at 0x100000(ND) or 0x200000(FM/DM)
                    if self.DUT_FAMILY == "stratix10" :
                        add = 0x100000
                    else :
                        add = 0x200000 + a2_startaddr
                cv_logger.info("MIP MAIN_ADD[%d]: 0x%08x"% (main_sec, add))
                self.MAIN_ADD.append(add)


            if self.MAIN_SEC_NUM >= 2 :
                index_start     = MAIN_IMAGE_POINTER['2nd_main_add'][index_offset] + a2_startaddr
                index_end       = index_start + MAIN_IMAGE_POINTER['2nd_main_add'][index_size]
                add = self.read_add(bitstream, index_start, index_end)
                # if address == 0, it means we are using relative address
                if add == 0 :
                    index_start = self.MAIN_ADD[1] + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add = self.MAIN_ADD[1] + self.read_add(bitstream, index_start, index_end)
                main_sec += 1
                cv_logger.info("MIP MAIN_ADD[%d]: 0x%08x"% (main_sec, add))
                self.MAIN_ADD.append(add)

            if self.MAIN_SEC_NUM >= 3 :
                index_start     = MAIN_IMAGE_POINTER['3rd_main_add'][index_offset] + a2_startaddr
                index_end       = index_start + MAIN_IMAGE_POINTER['3rd_main_add'][index_size]
                add = self.read_add(bitstream, index_start, index_end)
                if add == 0 :
                    index_start = self.MAIN_ADD[2] + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add = self.MAIN_ADD[2] + self.read_add(bitstream, index_start, index_end)
                main_sec += 1
                cv_logger.info("MIP MAIN_ADD[%d]: 0x%08x"% (main_sec, add))
                self.MAIN_ADD.append(add)

            if self.MAIN_SEC_NUM >= 4 :
                index_start     = MAIN_IMAGE_POINTER['4th_main_add'][index_offset] + a2_startaddr
                index_end       = index_start + MAIN_IMAGE_POINTER['4th_main_add'][index_size]
                add = self.read_add(bitstream, index_start, index_end)
                if add == 0 :
                    index_start = self.MAIN_ADD[3] + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add = self.MAIN_ADD[3] + self.read_add(bitstream, index_start, index_end)
                main_sec += 1
                cv_logger.info("MIP MAIN_ADD[%d]: 0x%08x"% (main_sec, add))
                self.MAIN_ADD.append(add)

            if puf_enable == 1:

                self.iid_puf_addr = PufAdd()
                self.iid_puf_addr.puf_extract_addr(bitstream, a2_startaddr)

        else:
            # Main address for non flash mode
            index_start = CMF_DESCRIPTOR['fw_sec_size'][index_offset]
            index_end   = index_start + CMF_DESCRIPTOR['fw_sec_size'][index_size]
            add = self.read_add(bitstream, index_start, index_end)

            self.MAIN_ADD = []

            # dummy add 0
            self.MAIN_ADD.append(0)

            main_sec = 1
            while (add < len(bitstream)) :
                cv_logger.info("MAIN_ADD[%d]: 0x%08x"% (main_sec, add))
                self.MAIN_ADD.append(add)

                # 'Read from bitstream file'
                index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]

                # 'base address of the main'
                add = add + self.read_add(bitstream, index_start, index_end)
                main_sec +=1
            self.MAIN_SEC_NUM = len(self.MAIN_ADD) - 1
            cv_logger.info("Total main section %d" %self.MAIN_SEC_NUM)

        # SSBL/TSBL start add
        index_start     = BOOTROM_DESCRIPTOR['ssbl_offset'][index_offset] + a2_startaddr
        index_end       = index_start + BOOTROM_DESCRIPTOR['ssbl_offset'][index_size]
        add = self.read_add(bitstream, index_start, index_end)
        cv_logger.info("%s_START_ADD: 0x%08x"% (self.SSBL_TSBL,add))
        self.SSBL_START_ADD = add

        # SSBL/TSBL end address
        index_start     = BOOTROM_DESCRIPTOR['ssbl_size'][index_offset] + a2_startaddr
        index_end       = index_start + BOOTROM_DESCRIPTOR['ssbl_size'][index_size]
        add             = add + self.read_add(bitstream, index_start, index_end) - 1
        cv_logger.info("%s_END_ADD: 0x%08x"% (self.SSBL_TSBL,add))
        self.SSBL_END_ADD = add

        # Trampoline start add
        index_start     = CMF_DESCRIPTOR['offset_trampol'][index_offset] + a2_startaddr
        index_end       = index_start + CMF_DESCRIPTOR['offset_trampol'][index_size]
        add = self.read_add(bitstream, index_start, index_end)
        cv_logger.info("TRAMPOLINE_START_ADD: 0x%08x"% add)
        self.TRAMPOLINE_START_ADD = add

        # Trampoline end address
        index_start     = CMF_DESCRIPTOR['size_trampoline'][index_offset] + a2_startaddr
        index_end       = index_start + CMF_DESCRIPTOR['size_trampoline'][index_size]
        add             = add + self.read_add(bitstream, index_start, index_end) - 1
        cv_logger.info("TRAMPOLINE_END_ADD: 0x%08x"% add)
        self.TRAMPOLINE_END_ADD = add

        # Sync start add
        self.SYNC_START_ADD=self.TRAMPOLINE_END_ADD
        if self.SYNC_START_ADD!=self.SSBL_START_ADD:
            cv_logger.info("SYNC_START_ADD: 0x%08x"% self.SYNC_START_ADD)

            # Sync end address
            self.SYNC_END_ADD=self.SSBL_START_ADD-1
            cv_logger.info("SYNC_END_ADD: 0x%08x"% self.SYNC_END_ADD)
        else:
            cv_logger.info("No Sync Block")


    '''
    Require  :  get_fw_add() must be called beforehand
    Input    :  bitstream -- the bytearray of the read bitstream
                location -- "first4k", -- randomly select addr at first 4KB (cmf descriptor)
                           "signature_desc", randomly select addr at signature descriptor
                           "hash_ssbl"          : BOOTROM_DESCRIPTOR["hash_ssbl"][0]
                           "hash_trampoline"    : CMF_DESCRIPTOR["hash_trampoline"][0]
                           "ssbl", randomly select addr at ssbl code
                           "trampoline", randomly select addr at trampoline code
                           "sync_first_word", randomly select addr at sync first word code
                           "sync_middle_word", randomly select addr at sync middle word code
                           "sync_last_word", randomly select addr at sync last word code
                           "main([1-4])_(desc|data)", eg. main1_data, randomly select addr
                              at the mentioned main section (descriptor or data)
                           actual addr in hex string, eg --> "0xABC"
                           actual addr in decimal, eg --> "10" or 10
                           ANYTHING ELSE IS UNSUPPORTED
                mult_byte -- specify the address to be a multiplier of a specific number of byte.
                             eg. if I put 4 bytes (32bit), then the output will always be a multiplier of 4 bytes.
                             DOES NOT WORK IF YOU INPUT YOUR OWN ADDRESS VALUE!!!
                cmf_copy -- I am not sure what is this for, need to ask Bee Ling
    Output   : returns a randomly selected address in the given location
    '''

    def select_addr(self, bitstream, location, cmf_copy=1, mult_byte=0):
        random.seed()
        offset = None
        if ( location == "first4k" ) :
            start   = 0         + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = 4*1024    + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at first 4k randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "signature_desc" ) :
            # First 48 bytes only
            start   = 1024*4        + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = 1024*4 + 47   + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at signature_desc randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "ssbl" ) :
            start   = self.SSBL_START_ADD   + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = self.SSBL_END_ADD     + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at %s randomly from 0x%08x to 0x%08x" %(self.SSBL_TSBL,start, end))

        elif ( location == "trampoline" ) :
            start   = self.TRAMPOLINE_START_ADD   + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = self.TRAMPOLINE_END_ADD     + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at trampoline randomly from 0x%08x to 0x%08x" %(start, end))


        elif ( location == "sync_first_word" ) :
            start   = self.SYNC_START_ADD   + ((cmf_copy-1)*256*1024)
            end     = self.SYNC_START_ADD+3     + ((cmf_copy-1)*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at sync first word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "sync_middle_word" ) :
            start   = self.SYNC_START_ADD+4   + ((cmf_copy-1)*256*1024)
            end     = self.SYNC_END_ADD-4     + ((cmf_copy-1)*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at sync middle word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "sync_last_word" ) :
            start   = self.SYNC_END_ADD-3   + ((cmf_copy-1)*256*1024)
            end     = self.SYNC_END_ADD     + ((cmf_copy-1)*256*1024)
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at sync last word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "hash_ssbl" ) :
            start   = 0         + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = 4*1024    + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = BOOTROM_DESCRIPTOR["hash_ssbl"][0]
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)

                cv_logger.info("Selected at hash_%s with mult_byte enabled: 0x%08x" %(self.SSBL_TSBL,offset))
            else:
                cv_logger.info("Selected at hash_%s: 0x%08x" %(self.SSBL_TSBL,offset))

        elif ( location == "hash_trampoline" ) :
            start   = 0         + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            end     = 4*1024    + ((cmf_copy-1)*self.DUT_FILTER.prefetcher_multiplier*256*1024)
            offset = CMF_DESCRIPTOR["hash_trampoline"][0]
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)

                cv_logger.info("Selected at hash_trampoline with mult_byte enabled: 0x%08x" %(offset))
            else:
                cv_logger.info("Selected at hash_trampoline: 0x%08x" %(offset))

        elif ( location == "last" ) :
            start   = 0
            end     = len(bitstream)
            offset  = len(bitstream)-1

            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected last byte from full bitstream - 0x%08x " %offset)


        else:
            searchObj = re.search( r'main([1-4])_(desc|data)', location)
            if searchObj:
                # cv_logger.debug("main ", searchObj.group(1))
                main_index = searchObj.group(1)
                max_main = len(self.MAIN_ADD) - 1
                assert_err ( int(main_index) <= max_main,
                    "ERROR :: Selected Section %s is out of range, Max Main Section is %d" % (main_index, max_main) )
                if ( searchObj.group(2) == "desc" ):
                    start = self.MAIN_ADD[int(main_index)]
                    end = self.MAIN_ADD[int(main_index)] + 0xFFF

                    main_offset_list = []
                    for each in MAIN_DESCRIPTOR:
                        if MAIN_DESCRIPTOR[each][2] == 1:
                            main_offset_list.append(MAIN_DESCRIPTOR[each][0])

                    random_ith = random.randint(0,len(main_offset_list)-1)
                    offset = self.MAIN_ADD[int(main_index)] + main_offset_list[random_ith]
                    if mult_byte:
                        offset = offset - (offset % mult_byte)
                        if offset < start or offset > end:
                            offset = offset + mult_byte
                        assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
                    cv_logger.info("Selected at Main %s Descriptor, with Main %s address 0x%08x, randomly from 0 to 0x1000" % (main_index, main_index, self.MAIN_ADD[int(main_index)]))

                else:
                    # 8k after the start of main section
                    # 1st 4k - main desc
                    # 2nd 4k - signature
                    start = self.MAIN_ADD[int(main_index)] + 0x1FFF
                    if ( int(main_index) == max_main) :
                        end = len(bitstream)-1
                    else:
                        end = self.MAIN_ADD[int(main_index)+1]-1
                    offset = random.randint(start, end)
                    if mult_byte:
                        offset = offset - (offset % mult_byte)
                        if offset < start or offset > end:
                            offset = offset + mult_byte
                        assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
                    cv_logger.info("Selected at Main %s Data, randomly from 0x%08x to 0x%08x" % (main_index, start, end))

            else:
                try:
                    searchObj = re.search( r'0x([0-9a-fA-F]*)', location)
                    if searchObj:
                        offset = int(location,16)
                    else:
                        offset = int(location)

                    start   = 0
                    end     = len(bitstream)
                    if mult_byte:
                        offset = offset - (offset % mult_byte)
                        if offset < start or offset > end:
                            offset = offset + mult_byte
                        assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
                    cv_logger.info("Selected offset from full bitstream - 0x%08x " %offset)

                except:
                    assert_err(0, "ERROR :: Unsupported item %s" %location )
        #------SatyaS Added Code making address Byte Alligned----------#
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
            cv_logger.debug("Original Address selected by test ---> 0x%x" %offset)
            temp_offset = int(offset/4)
            offset      = temp_offset*4
            cv_logger.debug("Byte Alligned adjusted Address    ---> 0x%x" %offset)

        return offset

    '''
    Require: get_fw_addr() to be called first
    Note   : only works with first keychain signed with one public user key
    Input  : bitstream -- bytearray of the bitstream
             section -- bitstream section we want to get the key entry from, can be
                       "firmware", "main1", .. main4""
             entry  -- key entry that we are interested in, can be
                       "root_0", "public_1", "block0_2", "desc", "chain_offset"
                       "desc" will return the offset to the signature block
                       "chain_offset" will return the offset of the current and next signature chain
    Output : offset -- the offset of the bitstream that leads to the key entry we are interested in
    '''
    def get_key_entry(self, bitstream, section, entry, chain=1):
        section_offset = None
        if section == "firmware":
            section_offset = 0
        else:
            searchObj = re.search( r'main([1-4])', section)
            section_offset = self.MAIN_ADD[int(searchObj.group(1))]

        if chain==1:
            signature_offset = "1st_sig_offset"
        elif chain==2:
            signature_offset = "2nd_sig_offset"
        elif chain==3:
            signature_offset = "3rd_sig_offset"
        elif chain==4:
            signature_offset = "4th_sig_offset"

        signature_block_offset = section_offset + 4*1024

        #offset to the field that stores 1st entry offset
        first_entry_offset =  signature_block_offset +  SIGNATURE_DESC[self.DUT_FAMILY][signature_offset][0]

        #offsets from the beginning of bitstream
        root_entry_0_offset = signature_block_offset + self.read_add(bitstream, first_entry_offset, first_entry_offset + SIGNATURE_DESC[self.DUT_FAMILY][signature_offset][1])

        public_entry_1_offset = root_entry_0_offset + self.read_add(bitstream , root_entry_0_offset + 4, root_entry_0_offset + 8)

        block0_entry_2_offset = public_entry_1_offset + self.read_add(bitstream , public_entry_1_offset + 4, public_entry_1_offset + 8)

        new_signature_chain_offset = block0_entry_2_offset + self.read_add(bitstream , block0_entry_2_offset + 4, block0_entry_2_offset + 8)

        entries_offsets = [root_entry_0_offset, public_entry_1_offset, block0_entry_2_offset]

        if entry == "desc":
            return signature_block_offset
        elif entry == "chain_offset":
            return [root_entry_0_offset, new_signature_chain_offset]

        searchObj = re.search( r'_([0-2])', entry)
        i = int(searchObj.group(1))
        return entries_offsets[i]




    '''
    Input    :  bitstream -- the bytearray of the pr bitstream
                location -- "first4k", -- randomly select addr at first 4KB (cmf descriptor)
                           "signature_desc", randomly select addr at signature descriptor
                           "ssbl", randomly select addr at ssbl code
                           "trampoline", randomly select addr at trampoline code
                           "main([1-4])_(desc|data)", eg. main1_data, randomly select addr
                              at the mentioned main section (descriptor or data)
                           actual addr in hex string, eg --> "0xABC"
                           actual addr in decimal, eg --> "10" or 10
                           ANYTHING ELSE IS UNSUPPORTED
                mult_byte -- specify the address to be a multiplier of a specific number of byte.
                             eg. if I put 4 bytes (32bit), then the output will always be a multiplier of 4 bytes.
                             DOES NOT WORK IF YOU INPUT YOUR OWN ADDRESS VALUE!!!
    Output   : returns a randomly selected address in the given location
    '''

    def select_pr_addr(self, bitstream, location, mult_byte=0):
        random.seed()
        offset = None
        if ( location == "first4k" ) :
            start   = 0
            end     = 4*1024
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at first 4k randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "signature_desc" ) :
            start   = 1024*4
            end     = 1024*4 + 47
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected at signature_desc randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( re.search( r'data', location) ):
            start   = 0x2000
            end     = len(bitstream)-1
            offset = random.randint(start, end)
            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected offset from data - 0x%08x " %offset)

        elif ( location == "last" ) :
            start   = 0
            end     = len(bitstream)
            offset  = len(bitstream)-1

            if mult_byte:
                offset = offset - (offset % mult_byte)
                if offset < start or offset > end:
                    offset = offset + mult_byte
                assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
            cv_logger.info("Selected last byte from full bitstream - 0x%08x " %offset)

        else:
            try:
                searchObj = re.search( r'0x([0-9a-fA-F]*)', location)
                if searchObj:
                    offset = int(location,16)
                else:
                    offset = int(location)

                start   = 0
                end     = len(bitstream)
                if mult_byte:
                    offset = offset - (offset % mult_byte)
                    if offset < start or offset > end:
                        offset = offset + mult_byte
                    assert_err(not (offset < start or offset > end), "ERROR :: Can't get offset within the given mult_byte of %d" %mult_byte)
                cv_logger.info("Selected offset from full bitstream - 0x%08x " %offset)

            except:
                assert_err(0, "ERROR :: Unsupported item %s" %location )

        return offset

    '''
    Require: get_fw_addr() + puf_enable = 1 to be called first
    Note   : only works if puf data is embedded in the rpd - else this will fail
    Input  : puf_block - specify which puf block i.e. 1,2 (first and second block respectively)
    Output : entries_offsets - returns all offsets of PUF Help Data addresses
    '''
    def get_puf_data_addr(self, puf_block):
        cv_logger.info("Generating list of PUF Addresses...")
        # PUF Addresses are as follow
        # 'iid_puf_magic'         : [0x000, 4, True],
        # 'reserve'               : [0x004, 4],
        # 'iid_puf_act'           : [0x608, 1536, True],
        # 'iid_puf_mac'           : [0x628, 32, True],
        # 'iid_puf_digest'        : [0x648, 32, True],
        offset = 0
        size = 1

        # puf_block check
        if ( puf_block == "1" ) or( puf_block == "2"):

            # Retrieve all offsets
            iid_puf_magic_start_offset = self.iid_puf_addr.PUF_DATA_ADDR[int(puf_block)]
            iid_puf_magic_end_offset   = iid_puf_magic_start_offset + PUF_BLOCK['PUF_HELP_DATA'][self.DUT_FAMILY]['iid_puf_magic'][size]
            iid_puf_act_start_offset   = iid_puf_magic_start_offset + PUF_BLOCK['PUF_HELP_DATA'][self.DUT_FAMILY]['iid_puf_act'][offset]
            iif_puf_act_end_offset     = iid_puf_act_start_offset + PUF_BLOCK['PUF_HELP_DATA'][self.DUT_FAMILY]['iid_puf_act'][size]
            iid_puf_mac_start_offset   = iif_puf_act_end_offset
            iif_puf_mac_end_offset     = iif_puf_act_end_offset + PUF_BLOCK['PUF_HELP_DATA'][self.DUT_FAMILY]['iid_puf_mac'][size]
            iid_puf_digest_start_offset= iif_puf_mac_end_offset
            iid_puf_digest_end_offset  = iid_puf_digest_start_offset + PUF_BLOCK['PUF_HELP_DATA'][self.DUT_FAMILY]['iid_puf_digest'][size]

            # Print Relevant Offsets
            cv_logger.info("iid_puf_magic_start offset : 0x%08x" %iid_puf_magic_start_offset)
            cv_logger.info("iid_puf_magic_end offset : 0x%08x" %iid_puf_magic_end_offset)
            cv_logger.info("iid_puf_act_start offset : 0x%08x" %iid_puf_act_start_offset)
            cv_logger.info("iif_puf_act_end offset : 0x%08x" %iif_puf_act_end_offset)
            cv_logger.info("iid_puf_mac_start_start offset : 0x%08x" %iid_puf_mac_start_offset)
            cv_logger.info("iif_puf_mac_end offset : 0x%08x" %iif_puf_mac_end_offset)
            cv_logger.info("iid_puf_digest_start offset : 0x%08x" %iid_puf_digest_start_offset)
            cv_logger.info("iif_puf_digest_end offset : 0x%08x" %iid_puf_digest_end_offset)

            # Return puf data address entries
            entries_offsets = [iid_puf_magic_start_offset, iid_puf_magic_end_offset, iid_puf_act_start_offset, iif_puf_act_end_offset, \
                               iid_puf_mac_start_offset, iif_puf_mac_end_offset, iid_puf_digest_start_offset, iid_puf_digest_end_offset]

            return entries_offsets

        else:
            assert_err(0, "ERROR :: Unsupported item : puf_block at %s" %puf_block )

    '''
    Require: get_fw_addr() + puf_enable = 1 to be called first
    Note   : only works if puf data is embedded in the rpd - else this will fail
    Input  : puf_block - specify which puf block i.e. 1,2 (first and second block respectively)
    Output : entries_offsets - returns all offsets of PUF Wkey Data addresses
    '''
    def get_puf_wkey_addr(self, puf_block):
        cv_logger.info("Generating list of PUF WKEY Addresses...")
        # PUF Addresses are as follow
        # 'magic_word'            : [0x00, 4, True],
        # 'reserve'               : [0x04, 4, False],
        # 'init_vector'           : [0x08, 16, True],
        # 'wrapped_key'           : [0x18, 32, True],
        # 'wkey_mac'              : [0x38, 32, True],
        # 'wkey_digest'           : [0x58, 32, True],
        offset = 0
        size = 1

        # puf_block check
        if ( puf_block == "1" ) or( puf_block == "2"):

            # Retrieve all offsets
            iid_puf_magic_start_offset          = self.iid_puf_addr.PUF_WKEY_ADDR[int(puf_block)]
            iid_puf_magic_end_offset            = iid_puf_magic_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['magic_word'][size]
            iid_puf_init_vector_start_offset    = iid_puf_magic_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['init_vector'][offset]
            iif_puf_init_vector_end_offset      = iid_puf_init_vector_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['init_vector'][size]
            iid_puf_wkey_start_offset           = iif_puf_init_vector_end_offset
            iif_puf_wkey_end_offset             = iid_puf_wkey_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['wrapped_key'][size]
            iid_puf_wkey_mac_start_offset       = iif_puf_wkey_end_offset
            iid_puf_wkey_mac_end_offset         = iid_puf_wkey_mac_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['wkey_mac'][size]
            iid_puf_wkey_dig_start_offset       = iid_puf_wkey_mac_end_offset
            iid_puf_wkey_dig_end_offset         = iid_puf_wkey_dig_start_offset + PUF_BLOCK['PUF_WKEY_DATA'][self.DUT_FAMILY]['wkey_digest'][size]

            # Print Relevant Offsets
            cv_logger.info("iid_puf_wkey_magic_start offset : 0x%08x" %iid_puf_magic_start_offset)
            cv_logger.info("iid_puf_wkey_magic_end offset : 0x%08x" %iid_puf_magic_end_offset)
            cv_logger.info("iid_puf_init_vector_start offset : 0x%08x" %iid_puf_init_vector_start_offset)
            cv_logger.info("iif_puf_init_vector_end offset : 0x%08x" %iif_puf_init_vector_end_offset)
            cv_logger.info("iid_puf_wkey_start offset : 0x%08x" %iid_puf_wkey_start_offset)
            cv_logger.info("iif_puf_wkey_end offset : 0x%08x" %iif_puf_wkey_end_offset)
            cv_logger.info("iid_puf_wkey_mac_start offset : 0x%08x" %iid_puf_wkey_mac_start_offset)
            cv_logger.info("iif_puf_wkey_mac_end offset : 0x%08x" %iid_puf_wkey_mac_end_offset)
            cv_logger.info("iid_puf_wkey_dig_start offset : 0x%08x" %iid_puf_wkey_dig_start_offset)
            cv_logger.info("iif_puf_wkey_dig_end offset : 0x%08x" %iid_puf_wkey_dig_end_offset)

            # Return puf data address entries
            entries_offsets = [iid_puf_magic_start_offset, iid_puf_magic_end_offset, iid_puf_init_vector_start_offset, iif_puf_init_vector_end_offset, \
                               iid_puf_wkey_start_offset, iif_puf_wkey_end_offset, iid_puf_wkey_mac_start_offset, iid_puf_wkey_mac_end_offset, \
                               iid_puf_wkey_dig_start_offset, iid_puf_wkey_dig_end_offset]

            return entries_offsets

        else:
            assert_err(0, "ERROR :: Unsupported item : puf_block at %s" %puf_block )

    '''
    Input    :  bitstream -- the bytearray of the read bitstream
                offset -- the offset to corrupt
                size -- number of size to read before corrupt
    Output   : returns the corrupted bitstream
    '''
    def corrupt_bitstream(self, bitstream, offset=0, size=1):
        cv_logger.info("Corrupted bitstream at offset 0x%08x with size %d" %(offset, size))

        assert_err( offset < len(bitstream), "ERROR :: offset 0x%08x cannot less than length of bitstream 0x%08x" %(offset, len(bitstream)) )
        corrupted_bitstream        = bytearray(bitstream)
        src_buff        = bitstream[offset:offset+size]

        # corrupt the particular location of the bitstream with 0xFF, the offset of 0x100 is chosen so that data falls in psuedo mid'
        buffer_count = 0

        while(buffer_count <  size):
            if(src_buff[buffer_count] != 0x0):
                break
            else:
                buffer_count = buffer_count + 1

        # 'if buffer counts reaches this values means all value are  zeros and we need corrupt it straight away by putting 1 in LSB'
        if(buffer_count == size):
            src_buff[0] = src_buff[0] | 0x1

        # 'Now create a Masking template'
        local_counter = 0x0
        while(True and (buffer_count < size)):

            local_mask_value = 0x1 << local_counter
            local_mask_used  = (~local_mask_value & 0xFF)
            local_temp_value = (src_buff[buffer_count] & local_mask_used)
            if(src_buff[buffer_count] != local_temp_value):
                'Force the new value'
                src_buff[buffer_count] = local_temp_value
                break
            else:
                local_counter = local_counter+1

        for ith in range( 0, len(src_buff)) :
            corrupted_bitstream[offset+ith] = src_buff[ith]

        return corrupted_bitstream

    '''
    Input    :  bitstream -- the bytearray of the read bitstream
                assigned_bitstream -- the replacement bitstream
                offset -- the offset to replace
    Output   : returns the corrupted bitstream with assigned bitstream at offset
    '''
    def corrupt_bitstream_assigned(self, bitstream, assigned_bitstream, offset=0):
        cv_logger.info("Corrupted bitstream at offset 0x%08x with assigned bitstream" %offset)

        assert_err( offset < len(bitstream), "ERROR :: offset 0x%08x cannot less than length of bitstream 0x%08x" %(offset, len(bitstream)) )
        corrupted_bitstream = bytearray(bitstream)

        for ith in range( 0, len(assigned_bitstream)) :
            corrupted_bitstream[offset+ith] = assigned_bitstream[ith]

        return corrupted_bitstream

    def generate_corrupted_bitstream(self, ori_file, new_file, corrupt, cmf_copy=1, size=1) :

        #read bitstream into byte array
        bitstream = self.read_bitstream(ori_file)

        offset = self.select_addr(bitstream=bitstream, location=corrupt, cmf_copy=cmf_copy)
        cv_logger.info("Generate corrupted bitstream at offset 0x%08x" % offset)
        corrupted_bitstream = self.corrupt_bitstream(bitstream, offset=offset, size=size)

        if (cmf_copy>1):
            # if (offset < self.MAIN_ADD[1]):
            cv_logger.info("Since CMF copy is %d, corruption at previos cmf copy is needed" % cmf_copy)
            while (cmf_copy>1):
                offset   = offset - (self.DUT_FILTER.prefetcher_multiplier*256*1024)
                corrupted_bitstream = self.corrupt_bitstream(corrupted_bitstream, offset=offset, size=size)
                cmf_copy = cmf_copy-1

        # Write into new_file
        fw1 = open(new_file, "wb")
        fw1.write(corrupted_bitstream)
        fw1.close()

        return offset

    '''
    Corrupt the section of bitstream given by [start, stop], the corruption is done randomly, but with the rightmost
    set bit of the original bitstream unset so we don't randomly get the same value as original value
    Note : the byte at stop index is exclusive, it will not be corrupted
    Input    :  bitstream -- the bytearray of the read bitstream
                new_file -- the replacement bitstream
                start_index -- the start offset to corrupted
                stop_index -- the end offset to be corrupted
                unset_last_bits -- unset the number of bits that is passed in here (from rightmost)
    Output   : returns corrupted field value
    '''
    def generate_random_last_set_bit_unset(self, bitstream, new_file, start_index, stop_index, seed, unset_last_bits=0):
        random.seed(seed)
        corrupted_section = bitstream[start_index:stop_index]
        num_bits = 8*(stop_index-start_index)
        field_value = int(binascii.hexlify(corrupted_section), 16)
        #get random value
        corrupted_field_value = random.randrange(0, 1 << (num_bits) - 1)
        #unset the original field's rightmost bit
        corrupted_field_value = ~((1 << unset_last_bits) - 1) & ~(field_value & (-field_value)) & corrupted_field_value

        corrupted_bitstream = bitstream
        for i in range(start_index, stop_index):
            corrupted_bitstream[i] = (corrupted_field_value & (0xFF << (i-start_index)*8)) >> (i-start_index)*8

        with open(new_file, "wb") as fw1:
            fw1.write(corrupted_bitstream)

        return corrupted_field_value

    '''
    Input    : cfg_status_nBOOTROM_DEBUG=True for FM
               cfg_status_nBOOTROM_DEBUG=False for Nd
    Output   : returns the bootstatus from device
    '''
    def debug_read_bootstatus(self,cfg_status_nBOOTROM_DEBUG=False,verdict_gen=True):

        self.jtag.access_ir(ir=23)
        bootstatus = self.jtag.access_dr(clock=32, dr=0)
        cv_logger.debug("Reading BOOTROM BOOTSTATUS: 0x%08X" %bootstatus)
        if(not cfg_status_nBOOTROM_DEBUG):
            pass
            #self.jtag.access_ir(ir=23)
            #bootstatus = self.jtag.access_dr(clock=32, dr=0)
            #cv_logger.info("Read bootstatus: 0x%08X" %bootstatus)
        else:
            local_success = []
            local_respond = self.jtag_send_sdmcmd(SDM_CMD['CONFIG_STATUS'])
            cv_logger.info("Send CONFIG_STATUS :: Response %s" %str(local_respond))
            local_lst_length = len(local_respond)


            if((cfg_status_nBOOTROM_DEBUG) and (verdict_gen)):
                if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
                    if(local_lst_length == 4):
                        local_success.append(True)
                        cv_logger.debug("In bootrom stage  <> OK")
                    else:
                        local_success.append(False)
                        cv_logger.error("Not occured in bootrom stage  <> KO")
                else:
                    if(local_lst_length == 2):
                        local_success.append(True)
                        cv_logger.debug("In bootrom stage  <> OK")
                    else:
                        local_success.append(False)
                        cv_logger.error("Did not occured in bootrom stage  <> KO")
                bootstatus = local_success
            else:
                bootstatus = True
        return bootstatus

    '''
    FPGA connector - master_read_32 command
    Input: addr - Address you want to read from
            size - size of read data
    '''
    def fpga_read_32_fail(self, addr, size, success=1, exp_err=None):

        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first\n")
        read_word=""
        try:
            cv_logger.info("Perform master_read_32 on address : %d in size %d" %(addr, size))
            read_word = self.fpga.read(addr, size)
            if size != 1:
                cv_logger.info("32-bit word returned %s" %read_word)
            else:
                cv_logger.info("32-bit word returned %d" %read_word)
        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION :: %s" %local_respond)
            if success:
                print_err("ERROR :: Failed to do asic read UNEXPECTEDLY")
                raise e
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, local_respond)):
                    cv_logger.info("Failed to read asic proto as EXPECTED")
                else:
                    print_err("ERROR :: Failed to read asic proto, but different error as expected")
                    raise e

        else: #no error
            if success:
                cv_logger.info("Successfully performed asic read as expected")
            else:
                #don't to assert_err, that will cause the reg.rout to be edited, which may not be what we want
                assert False, "WARNING ::  Successfully performed asic read when failure expected"

        return read_word

    '''
    FPGA connector - master_read_32 command
    Input: addr - Address you want to read from
            size - size of read data
    '''
    def fpga_read_32(self, addr, size):

        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first\n")

        cv_logger.info("Perform master_read_32 on address : %d in size %d" %(addr, size))
        read_word = self.fpga.read(addr, size)
        if size != 1:
            cv_logger.info("32-bit word returned %s" %read_word)
        else:
            cv_logger.info("32-bit word returned %d" %read_word)

        return read_word

    '''
    FPGA connector - master_write_32 command
    Input:  addr - Address you want to write to
            value - value you want to write into the address
    '''
    def fpga_write_32(self, addr, value):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first\n")

        cv_logger.info("Perform master_write_32 on address %d with value %d" %(addr, value))
        write_word = self.fpga.write(addr, value)

    '''
    ASIC PROTO Start Action Function
    It starts a specific action such as start register readback, stop register readback... etc.
    '''
    def start_asic_proto_action(self, addr, value, success=1, exp_err=None):
        assert_err(self.fpga!=None, "ERROR :: You must get FPGA connector first\n")

        cv_logger.info("Start action %d on address 0x%x" %(value, addr))
        self.fpga_write_32(addr=addr, value=value)
        if success:
            status = self.fpga_read_32(addr=addr, size=1)
            cv_logger.info("status is %d" %status)
            while(status != 0):
                cv_logger.info("action %d is busy" %value)
                status = self.fpga_read_32(addr=addr)
            cv_logger.info("action %d is done" %value)
        else:
            status = self.fpga_read_32_fail(addr=addr, size=1, success=success, exp_err=exp_err)



    '''
    Input: iteration -- number of times to read
            addr -- the address to read from
    Optional: success -- 1 if asic read should be successful, 0 if expected fail
              exp_err -- expected error from framework if success = 0
    '''
    def start_asic_read(self, iteration, addr, success=1, exp_err=None):

        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first\n")
        cv_logger.info("Success set as %d" %success )
        cv_logger.info("Total iterations: %d" %iteration)

        try:
            for i in range(iteration):
                cv_logger.info("Iteration %d" %i)
                int_number = self.fpga_read_32(addr=addr, size=4)
                cv_logger.info("Int_number in list : %s" %int_number)
                for each in int_number:

                    hex_number =  '0x'+ '{:08x}'.format(each)
                    binary_number = '{:032b}'.format(each)
                    cv_logger.info("32-bit word returned in hex is %s" %hex_number)
                    cv_logger.info("32-bit word returned in binary is %s" %binary_number)
                    cv_logger.info("iteration %d" %i)
                cv_logger.info("-----------------------------------------------------")

                i += 1

        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION :: %s" %local_respond)
            if success:
                print_err("ERROR :: Failed to do asic read UNEXPECTEDLY")
                raise e
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, local_respond)):
                    cv_logger.info("Failed to read asic proto as EXPECTED")
                else:
                    print_err("ERROR :: Failed to read asic proto, but different error as expected")
                    raise e

        else: #no error
            if success:
                cv_logger.info("Successfully performed asic read as expected")
            else:
                #don't to assert_err, that will cause the reg.rout to be edited, which may not be what we want
                assert False, "WARNING ::  Successfully performed asic read when failure expected"

    '''
    Fpga connector - read_command_fifo_info and print out
    '''
    def fpga_read_command_fifo_info(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        fifo_info = self.fpga.read_command_fifo_info()
        cv_logger.info("Command FIFO info: 0x%08X" % fifo_info)

    '''
    Fpga connector - read_interrupt_status and print out
    '''
    def fpga_read_interrupt_status(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        status = self.fpga.read_interrupt_status()
        cv_logger.info("Interrupt status before PR command sent: 0x%08X" % status)


    '''
    Fpga connector - read_respond
    Output: return the responds
    '''
    def fpga_read_respond(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")
        try:
            responds = self.fpga.read_respond()
        except:
            assert_err(0, "ERROR :: Failed to read FPGA responds")

        responds_print = []
        for i in range(len(responds)) :
            responds_print.append("0x%08X" % responds[i])
        cv_logger.info("Responses: %s" % responds_print)
        return responds

    '''
    Fpga connector - sends SDM command
    Note    : this command is send sdm commadn thru FPGA connector
    '''
    def fpga_send_sdmcmd(self, sdm_cmd, *arg):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")
        input_length = len(arg)
        input_id = 0 #does not matter
        input_client = 0xe #14 for fpga mbox
        input_cmd = sdm_cmd
        header = input_cmd | (input_length << 12) | (input_id << 24) | (input_client << 28)
        self.fpga.write_command(header, *arg)
        # responds = self.fpga_read_respond()
        # return responds

    '''
    Fpga connector - sends CANCEL command via FPGA mailbox
    Note    : this command is send cancel command thru FPGA connector
    '''
    def fpga_send_cancel(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("")
        cv_logger.info("Send cancel command via FPGA MAILBOX IP")
        self.fpga_send_sdmcmd(SDM_CMD['CANCEL'])
        responds = self.fpga_read_respond()
        assert_err(responds[0] == 0, "ERROR :: RECONFIG response is not [0]!")
    '''
    Fpga connector - trigger pr
    Output: return the responds
    '''
    def fpga_trigger_pr(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("Trigger PR thru FPGA BFM")
        # self.fpga.write_command(SDM_CMD['RECONFIG'])
        self.fpga_send_sdmcmd(SDM_CMD['RECONFIG'])
        responds = self.fpga_read_respond()
        assert_err(responds[0] == 0, "ERROR :: RECONFIG response is not [0]!")

    '''
    Fpga connector - rsu_switch_image
    Output: return the responds
    '''
    def fpga_rsu_switch_image(self, address):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX : Update RSU to 0x%x "%address)
        address_high = (address >> 32) & 0xffffffff
        address_low = address & 0xffffffff

        self.fpga_send_sdmcmd(SDM_CMD['RSU_SWITCH_IMAGE'], address_low, address_high)

    '''
    Fpga connector - sync
    '''
    def fpga_sync(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")
        cv_logger.info("Sync with SDM via FPGA Mailbox")
        random_value = random.randint(0, 0xFFFFFFFF)
        self.fpga.write_command(0xF0001001, random_value)
        responds = self.fpga_read_respond()
        assert_err(len(responds) == 2, "ERROR :: Expect 2 Status Responds but found %s" % responds)
        assert_err(responds[1] == random_value, "ERROR :: Expect second sync respond to be 0x%08X but found 0x%08X" % (random_value, responds[1]))

    '''
    Fpga connector - reset dma
    '''
    def fpga_reset_dma(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        self.fpga.reset_dma()

    '''
    Fpga connector - prepare data
    '''
    '''
    Input   :   file_path -- path for the bitstream file (usually rbf file)
                ast -- 1 if ast for check_ram(), 0 otherwise
                offset -- offset to prepare data for avst
    Optional: check_ram -- 1 if want to check the bitstream written into RAM, if not 0
    Modify  : self, prepares AVST configuration by writing bitstream into RAM
    Output  : returns the length of the bitstream (number of bytes)
    '''
    def fpga_prepare_data(self, file_path, check_ram=0, ast=0, offset=0):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        #read bitstream into byte array
        bitstream = self.read_bitstream(file_path)

        #prepare the RAM
        cv_logger.info("Writing Bitstream from %s into RAM..." % file_path)
        self.dut.test_time()
        self.fpga.prepare_data(bitstream, offset)
        self._prepared_file_path = file_path
        cv_logger.info("Time to write data into RAM: %s" % self.dut.elapsed_time())

        #if user specified, check the RAM bistream
        if check_ram:
            check_ram(file_path=file_path, ast=ast)
        else:
            cv_logger.warning("FPGA RAM bitstream not checked")
            self._lib_delay()

        cv_logger.info("Finished preparing data into FPGA BFM")

        return len(bitstream)

    '''
    Input   : length, number of bytes of bitstream we want to send from RAM
    Optional: success -- 1 if sending should success, 0 otherwise
              exp_err -- expected error message from framework if success = 0
                         if the acquired error message contains exp_err, then it is handled
              offset -- byte offset to start sending bitstream, default 0
              timeout -- timeout in seconds, default 10s
    Modify  : self, sends the bitstream via AVST
    '''
    def fpga_send_data(self, length, success=1, exp_err=None, offset=0, timeout=10):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("C%d :: Sending Bitstream Via FPGA Mailbox" %(self._config_counter))
        self._config_counter = self._config_counter + 1

        try:
            self.dut.test_time()
            status = self.fpga.send_data(offset, length, timeout)
        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION ::%s" %local_respond)
            if success:
                print_err("ERROR :: Failed to load bitstream UNEXPECTEDLY")
                raise e
            else:
                assert_err(exp_err!=None, "ERROR :: Please provide expected error message if you expect an error!")
                if(re.search(exp_err, local_respond)):
                    cv_logger.info("Failed to load the bitstream as EXPECTED")
                else:
                    if os.environ.get("PYCV_PLATFORM") == 'simics' :
                        # For now it is ok to allow different Error (as long as it is still an error)
                        # Simics is not SysCon anyway, will unify the error after this
                        print("Simics Warning :: Expected error is \"%s\", but found \"%s\"" % (exp_err, local_respond))
                    else :
                        print_err("ERROR :: Failed to load bitstream, but different error as expected")
                        raise e
        else:   #if no error
            assert_err(success, "ERROR ::  Successfully loaded bitstream when FAIL EXPECTED")
            cv_logger.info("Successfully loaded bitstream as expected")
            # cv_logger.info("PR configuration via FPGA Mailbox IP completed with response: %s" %status)

        cv_logger.info("Finished sending PR bitstream")

    '''
    This is for the case of PR_FPGA_BAD when AVST data might be successfully sent through or it might not (andor_reg_pr_mlab_vidon_fwval)
    Input   : length, number of bytes of bitstream we want to send from RAM
    Optional: success -- 1 if sending should success, 0 otherwise
              exp_err -- expected error message from framework if success = 0
                         if the acquired error message contains exp_err, then it is handled
              offset -- byte offset to start sending bitstream, default 0
              timeout -- timeout in seconds, default 10s
    Modify  : self, sends the bitstream via AVST
    '''
    def fpga_send_data_pr_bad(self, length, exp_err=None, offset=0, timeout=10):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("C%d :: Sending Bitstream Via FPGA Mailbox" %(self._config_counter))
        self._config_counter = self._config_counter + 1

        try:
            self.dut.test_time()
            status = self.fpga.send_data(offset, length, timeout)
        except Exception as e:
            local_respond = self.dut.get_last_error()
            cv_logger.error("EXCEPTION ::%s" %local_respond)

            if(re.search(exp_err, local_respond)):
                cv_logger.info("Failed to load the bitstream as EXPECTED for pr_fpga_bad case")
            else:
                if os.environ.get("PYCV_PLATFORM") == 'simics' :
                    # For now it is ok to allow different Error (as long as it is still an error)
                    # Simics is not SysCon anyway, will unify the error after this
                    print("Simics Warning :: Expected error is \"%s\", but found \"%s\"" % (exp_err, local_respond))
                else :
                    print_err("ERROR :: Failed to load bitstream, but different error as expected")
                    raise e
        else:   #if no error

            cv_logger.info("Successfully loaded bitstream as expected for pr_fpga_bad case")


        cv_logger.info("Finished sending PR bitstream")

    '''
    Input   : file_path -- path for the bitstream file (usually rbf file)
              ast -- 1 if assert, 0 otherwise
    Modify  : self, prepares FPGA PR configuration by writing bitstream into RAM
    Output  : return 1 if good, 0 if bad
    '''
    def check_ram(self, file_path, ast=0):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        bitstream_buffer = self.read_bitstream(file_path)
        bitstream_length = len(bitstream_buffer)

        cv_logger.info("Checking RAM...")
        local_pass = True
        read_back_data=[]
        self.dut.test_time()
        read_back_data = self.fpga.read_back(0x0,bitstream_length)
        cv_logger.info("Time to read data from RAM: %s" % self.dut.elapsed_time())
        assert_err((not ast) or (len(read_back_data) == bitstream_length),
            "ERROR :: Readback RAM data length is %d, expected %d bytes"
            %(len(read_back_data), bitstream_length))

        if len(read_back_data) != bitstream_length:
            print_err("ERROR :: Readback RAM data length is %d, expected %d bytes"
                %(len(read_back_data), bitstream_length))

        self.dut.test_time()
        for i in xrange(bitstream_length):
            if(bitstream_buffer[i]^read_back_data[i]):
                local_pass = False
                cv_logger.error("Expected data = 0x%x; read data = 0x%x; offset=%d" %(bitstream_buffer[i],read_back_data[i],i))
        cv_logger.info("Time to Compare content: %s" % self.dut.elapsed_time())

        assert_err(((not ast) or local_pass),
            "ERROR :: Readback RAM data is different than expected")

        if local_pass:
            cv_logger.info("Data written into RAM looks good")
        else:
            print_err("ERROR :: Readback RAM data is different than expected")
        return local_pass

    '''
    Fpga connector - qspi_open
    Output: return the responds
    '''
    def fpga_qspi_open(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX send QSPI_OPEN")
        self.fpga_send_sdmcmd(SDM_CMD['QSPI_OPEN'])
        responds = self.fpga_read_respond()
        # assert_err(responds[0] == 0, "ERROR :: FPGAMBOX --> QSPI_OPEN response is not [0]!")
        return len(responds) == 1 and responds[0] == 0

    '''
    Fpga connector - qspi_open
    Output: return the responds
    '''
    def fpga_qspi_close(self):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX send QSPI_CLOSE")
        self.fpga_send_sdmcmd(SDM_CMD['QSPI_CLOSE'])
        responds = self.fpga_read_respond()
        # assert_err(responds[0] == 0, "ERROR :: FPGAMBOX --> QSPI_CLOSE response is not [0]!")
        return len(responds) == 1 and responds[0] == 0

    '''
    Fpga connector - qspi_open
    Output: return the responds
    '''
    def fpga_qspi_set_cs(self, cs_setting):
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX send QSPI_SET_CS %d"%cs_setting)
        self.fpga_send_sdmcmd(SDM_CMD['QSPI_SET_CS'], cs_setting)
        responds = self.fpga_read_respond()
        # assert_err(responds[0] == 0, "ERROR :: FPGAMBOX --> QSPI_SET_CS response is not [0]!")
        return len(responds) == 1 and responds[0] == 0

    '''
    Functionality   : Fpga connector to Erase QSPI flash
    Input           :   1. Start address (1 word)
                        2. Number of bytes to erase (either match or multiples of erase size options in QSPI_SETUP)
    Return          : Status
    '''
    def fpga_qspi_erase(self, address, size) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX send QSPI_ERASE %d %d "%(address, size / 4))
        self.fpga_send_sdmcmd(SDM_CMD['QSPI_ERASE'], address, size / 4)
        responds = self.fpga_read_respond()
        # assert_err(responds[0] == 0, "ERROR :: FPGAMBOX --> QSPI_ERASE failed at 0x%08x" % address)
        status = len(responds) == 1 and responds[0] == 0
        if not status :
            cv_logger.warning("QSPI_ERASE Failed at 0x%08x" % address)
        return status

    '''
    Functionality   : Fpga connector to Erase QSPI flash for a sector
    Input           :   1. Start address (1 word)
    Return          : Status
    '''
    def fpga_qspi_sector_erase(self, address) :

        return self.fpga_qspi_erase(address, 64<<10)

    '''
    Functionality   : Fpga connector to Erase QSPI flash for a sector
    Input           :   1. Start address (1 word)
    Return          : Status
    '''
    def fpga_qspi_4k_erase(self, address) :

        return self.fpga_qspi_erase(address, 4<<10)

    '''
    Functionality   : Fpga connector to Generic send opcode without no data
    Input           :   1. Flash opcode
    Return          : None
    '''
    def fpga_qspi_send_device_op(self, opcode) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        self.fpga_send_sdmcmd(SDM_CMD['QSPI_SEND_DEVICE_OP'], opcode)
        responds = self.fpga_read_respond()
        return len(responds) == 1 and responds[0] == 0


    '''************************************************************************************************************************
        Write enable (0x06)
    ************************************************************************************************************************'''
    def fpga_qspi_write_enable(self) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        status = self.fpga_qspi_send_device_op(0x06)
        if not status :
            cv_logger.warning("Failed to issue Write Enable")
        return status

    '''
    Functionality   : Fpga connector to Write flash
    Input           :   1. Start address (1 word)
                        2. Data to be written (1 or more words)
    Return          : Status
    '''
    def fpga_qspi_write(self, address, *data) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        # cv_logger.info("FPGAMBOX send QSPI_WRITE %d %d "%(address, size / 4))
        data_size = len(data)
        assert_err( data_size <= 1024, "ERROR :: data_size more than 1024")

        self.fpga_send_sdmcmd(SDM_CMD['QSPI_WRITE'], address, data_size, *data)
        responds = self.fpga_read_respond()
        status = len(responds) == 1 and responds[0] == 0
        if not status :
            cv_logger.warning("QSPI_WRITE Failed at 0x%08x" % address)
        return status

    '''
    Functionality   : Fpga connector to read flash
    Input           :   1. Start address (1 word)
                        2. Number of words to read (1 word)
    Return          : Data
    ************************************************************************************************************************'''
    def fpga_qspi_read(self, address, size) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        self.fpga_send_sdmcmd(SDM_CMD['QSPI_READ'], address, size)
        responds = self.fpga_read_respond()
        status = (responds[0] >> 12 & 0x7ff) == size and (responds[0] & 0x3ff) == 0
        if not status :
            self.platform.print_warning_msg("QSPI_READ Failed at 0x%08x" % address)
        return status, responds

    '''
    Fpga connector - add_new_qspi_image
    Functionality   : Verify flash content
        Input    :  rpd_file_name - single image rpd to update
                    start_address - QSPI address to write
                    update -    1 for update mode that involved QSPI_ERASE;
                                0 for add to new flash offset that do not need QSPI_ERASE
                    verify - Read back and verify the flash content
        Output   : returns status
    '''
    def fpga_add_new_qspi_image(self, rpd_file_name, start_address=0, update=True, verify=False) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("FPGAMBOX to program QSPI Flash")

        status = True
        bitstream = self.read_bitstream(rpd_file_name)
        bitstream_size = len(bitstream)

        # 1. Erase
        if update:
            cv_logger.info("Erasing flash...")
            offset = 0
            while status and offset < bitstream_size :
                if os.environ['QUARTUS_VERSION'] == '18.0':
                    status = self.fpga_qspi_sector_erase(start_address + offset)
                    offset +=  64<<10
                else:
                    status = self.fpga_qspi_4k_erase(start_address + offset)
                    offset +=  4<<10
        else:
            cv_logger.info("Skip QSPI_ERASE")

        # 2. Program
        if status :
            offset = 0
            max_data = 4096
            cv_logger.info("Programming %s..." % rpd_file_name)
            while status and offset < bitstream_size :
                # Check whether there is 4K bytes or less data
                if (offset + max_data) <= bitstream_size :
                    bytes_to_pgm = max_data
                else :
                    bytes_to_pgm = bitstream_size - 1
                data_words = []
                for i in range (offset/4, (offset + bytes_to_pgm)/4) :
                    # convert bytes to words
                    data_word = bitstream[i * 4] << 24 | bitstream[i * 4 + 1] << 16 | bitstream[i * 4 + 2] << 8 | bitstream[i * 4 + 3]
                    # reverse bit order
                    reversed_data = 0
                    if data_word != 0xFFFFFFFF and data_word != 0:
                        for j in xrange(32) :
                            if (data_word >> j) & 1 :
                                reversed_data |= 1 << (31 - j)
                    else :
                        reversed_data = data_word
                    data_words.append(reversed_data)
                # Program if data is not blank
                if data_words != ([0xFFFFFFFF] * len(data_words)) :
                    status = self.fpga_qspi_write(start_address + offset, *data_words)
                offset += bytes_to_pgm
            cv_logger.info("Programming completed")

        # 3. Verify
        if status and verify :
            status = self.fpga_qspi_verify(rpd_file_name, start_address)

        return status

    '''
    Fpga connector - qspi_verify
    Functionality   : Verify flash content
        Input           :   1. RPD File
                            2. Start address (1 word)
        Return          : Status
    '''
    def fpga_qspi_verify(self, rpd_file_name, start_address=0) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        cv_logger.info("Verifying flash content with %s from 0x%08x..." % (rpd_file_name, start_address))
        bitstream = self.read_bitstream(rpd_file_name)
        [status, read_data] = self.fpga_read_flash(len(bitstream), start_address, bitstream)
        return status

    def fpga_read_flash (self, n_bytes, start_address=0, expected_data=None) :
        assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector first")

        status = True
        offset = 0
        max_data = 4096
        read_data = bytearray()
        self.platform.start_progress()
        while status and offset < n_bytes :
            # Check whether there is 4K bytes or less data
            if (offset + max_data) <= n_bytes :
                bytes_to_read = max_data
            else :
                bytes_to_read = n_bytes
            [status, response] = self.fpga_qspi_read(start_address + offset, bytes_to_read / 4)
            response_bytes = bytearray(bytes_to_read)
            for i in range (1, len(response)) :
                # reverse bit order
                reversed_response = 0
                if response[i] != 0xFFFFFFFF and response[i] != 0 :
                    for j in xrange (32) :
                        if (response[i] >> j) & 1 :
                            reversed_response |= 1 << (31 - j)
                else :
                    reversed_response = response[i]
                # convert word to byte
                for k, n in enumerate([24, 16, 8, 0]) :
                    response_bytes[(i-1) * 4 + k] = (reversed_response >> n & 0xff)
            read_data += response_bytes
            if status and expected_data != None :
                if read_data[offset:offset+bytes_to_read] != bytearray(expected_data[offset:offset+bytes_to_read]) :
                    for x in range(bytes_to_read) :
                        bitstream_address = offset + x
                        if read_data[bitstream_address] != expected_data[bitstream_address] :
                            cv_logger.error("Data mismatched at 0x%08x: Expected 0x%02x but found 0x%02x" % ((start_address + offset + x), expected_data[bitstream_address], read_data[bitstream_address]))
                            status = False
            offset += bytes_to_read
            self.platform.print_progress_msg((offset * 100)/n_bytes)
        self.platform.end_progress()
        return status, read_data

    '''
    Input   : external_clock_in_mhz -- 125 by default to drive external clock (125mhz)
            : clk_source -- Select CA or CLKGEN1 only as clock source. By default is CLKGEN1. Other clk_source shall assert error.
    Modify  : this function only works in mudv platform (courage ridge)
              drive external clock based on user design's device_init_clock_hz
    '''
    def drive_external_clock(self, external_clock_in_mhz=125, clk_source="CLKGEN1"):

        if not self._sdmio.platform == 'mudv':
            cv_logger.info("Skip to call drive_external_clock on non-mudv platform")
            return

        # reg_copy_files copy from somewhere else.
        supported_clk_files = [
            'mudv_25mhz.txt',
            'mudv_50mhz.txt',
            'mudv_100mhz.txt',
            'mudv_125mhz.txt'
        ]

        sel_clk_source = {
            'CA'        :2,
            'CLKGEN1'   :4
        }
        
        # selection clock frequency supplied by CA with supported 4mux devices only
        # 0 : 125Mhz
        # 1 : 100Mhz
        # 2 : 25Mhz
        sel_ca_clk_freq = {
            125:0,
            100:1,
            25:2,
        }
        device_4mux = os.environ.get('DUT_BOARD_4MUX_EN')

        if clk_source not in sel_clk_source:
            cv_logger.warning('WARNING :: Clock source selected is %s' % clk_source)
            raise Exception ('Supported clock source is %s. Please provide the valid clock source to drive external clock in mudv' % list(sel_clk_source.keys()))

        if (device_4mux == None):
            device_4mux = "0"
            cv_logger.info("WARNING :: DUT_BOARD_4MUX_EN is not found in arc board resource attribute!! Set 4mux as not supported")

        if device_4mux != "0":
            # HSD15013974684
            # Selection clock source supplied to device's OSC_CLK1
            # 0 : High-Z (DUT board Switch is used for Clock Mux selector)
            # 1 : External clock source (SMB connector)
            # 2 : Clock source from CA (Default 125Mhz)
            # 3 : Clock source from BMC (Default 100Mhz) 
            # 4 : Clock source from BaseBoard Clock Generator (Default 125Mhz)
            self.pll = self.dut.get_connector("pll")
            assert_err(self.pll != None, "ERROR :: Cannot open pll Connector")
            self.pll.set_osc_clk_4mux(sel_clk_source[clk_source])
            clk_4mux = self.pll.read_osc_clk_4mux()
            assert_err(clk_4mux == sel_clk_source[clk_source], "ERROR :: Set clk 4mux failed")
            
        if clk_source == "CLKGEN1" or device_4mux == "0":
            input_clk_files = 'mudv_' + str(external_clock_in_mhz) + 'mhz.txt'
            if input_clk_files not in supported_clk_files:
                cv_logger.info('WARNING :: supported clock is in %s mhz' % [25, 50, 100, 125])
                raise Exception ('Please provide valid clock to drive external clock in mudv')

            if not os.path.isfile(input_clk_files):
                raise Exception ('cannot find %s' % input_clk_files)

            assert self.bmc is not None, "Get BMC connector failed"
            self.bmc.set_bmc_support_i2c2(1)
            cv_logger.info("driving external clock %d mhz in mudv platform" % external_clock_in_mhz)
            clkgen_ret = self.bmc.config_clkgen(clk_name="CLK_1", clk_file=input_clk_files)
            assert_err( clkgen_ret == 0, "FAIL: bmc.config_clkgen return code: %d" % clkgen_ret)
            clkgen_fout = self.get_clkgen_fout()
            assert_err( clkgen_fout == 1000000*external_clock_in_mhz, "FAIL: clock frequency mismatch, expected %d Hz but return %d Hz" %(1000000*external_clock_in_mhz, clkgen_fout))
        elif clk_source== "CA":
            if(external_clock_in_mhz not in sel_ca_clk_freq):
                cv_logger.info('WARNING :: supported clock is in %s mhz' % [25, 100, 125])
                raise Exception ('Please provide valid clock to drive external clock in mudv')
                
            cv_logger.info("Setting clock frequency supplied by CA with selection %d " % sel_ca_clk_freq[external_clock_in_mhz])
            # Selection clock frequency supplied by CA tp device's OSC_CLK1. This api is only valid when CA is set as clock source on board
            # 0 : 125Mhz
            # 1 : 100Mhz
            # 2 : 25Mhz
            self.pll.set_osc_clk_freq(sel=sel_ca_clk_freq[external_clock_in_mhz])


    '''
    Input           : clk_name -- Clock gen names. 'CLK_1' by default
                      port_index -- Output port index. 4 by default   
    Functionality   : this function only works in mudv platform
                      Read one of output port's clock frequency from any clock generator being queried
    Return          : CLKGEN data in Hz
    '''
    def get_clkgen_fout(self, clk_name='CLK_1', port_index=4):

        if not self._sdmio.platform == 'mudv':
            cv_logger.info("Skip to call get_clkgen_fout on non-mudv platform")
            return
        assert self.bmc is not None, "Get BMC connector failed"
        self.bmc.set_bmc_support_i2c2(1)
        clkgen_ret=self.bmc.read_clkgen_fout(clk_name, port_index)
        cv_logger.info("CLKGEN %s output port index %d frequency is %d Hz" %(clk_name, port_index, clkgen_ret))
        return clkgen_ret
