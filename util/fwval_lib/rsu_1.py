from fwval_lib.common import *
from fwval_lib.configuration.qspi import QspiTest
from fwval_lib.security.puf import PufAdd
import cv_logger
import os
import pycv as fwval
import random
import re

revision = "$Revision: #9 $"
__version__ = 0
try: __version__ = int([''.join([str(s) for s in [c for c in revision] if s.isdigit()])][0])
except: pass
cv_logger.info("%s current rev: #%s" % (__name__, __version__))
cv_logger.info("%s source: %s" % (__name__, __file__))

###########################################################################################
#    RSU
###########################################################################################

#RsuTest will support all QspiTest capabilities, with addition of RSU ones as defined here
class RsuTest(QspiTest):
    '''
        Input   : configuration, msel, for fwval.platform_init(), default None and 8 respectively
                  config_done_sdmio, init_done_sdmio, have default values 16 and 0
                  rev -- used for specify revision (string contain a,b,c, etc). if don't care
                         then leave at empty string
                  daughter_card -- Set dc=1 if the test is using a physical QSPI flash. If no value is
                  given, Sdmio Class will auto assign a value based on the platform
        Mod     : self -- initialize the test object
        Note    : the rev variable is used when there are differences between revisions.
                  eg. for RevA, CONFIG_STATUS command will fail at IDLE state. So we must
                  input RevA when our test call CONFIG_STATUS in IDLE state.
                  (I recommend putting your rev in, you may forget that RevA does not work
                  in some cases. At least the code will tell you)
    '''
    def __init__(self, configuration="qspi", msel=9, rev="", daughter_card=None, config_done_sdmio="", init_done_sdmio=None):
        #calls the super constructor (JtagTest constructor)

        super(RsuTest, self).__init__(configuration=configuration, msel=msel, rev=rev, daughter_card=daughter_card,
            config_done_sdmio=config_done_sdmio, init_done_sdmio=init_done_sdmio)

        # Factory pin workaround for emulator MAX 10 BFM
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            # Power up the board and wait for the board to become stable
            self.power_up_reset()
            self.verify_pin(ast=0,wait_time_out_check=True)

            # FM6 Emulator's BFM is special
            # because it combined all kind of QSPI and AVSTs configuration mode into one BFM
            # and a new sdmio_tri MUX has been introduced into the design which is default to High-Z.
            # we need to set sdmio_tri MUX to allow sdm_io10 to pass through as output to top level
            master_service = self.qspi.platform.get_bfm_master_service()
            assert_err(len(master_service), "ERROR :: Failed to get master path")

            EMULATOR_MAX10_BFM_SDMIO_TRI_REG = 0x21720
            command = "master_read_32 %s 0x%08X 1" % (master_service, EMULATOR_MAX10_BFM_SDMIO_TRI_REG)
            responses = self.qspi.platform.send_system_console(command)
            value = int(responses[0], 0)

            # Set sdmio_tri[10] to zero
            value = value & 0xFFFFFBFF

            command = "master_write_32 %s 0x%X 0x%X" % (master_service, EMULATOR_MAX10_BFM_SDMIO_TRI_REG, value)
            self.qspi.platform.send_system_console(command)

            cv_logger.info("fwval_lib RsuTest emulator init done.")
        else:
            cv_logger.info("fwval_lib RsuTest board init done.")


    '''
    Input   : cmf_state -- 1 we expect the device to be in CMF state, 0 means still in bootrom
              2 means it can be in either state (if in cmf state, will check against expected status.
              If bootrom stage, don't care)
              pr -- send config_status if False, send reconfig_status if True
              ast -- 0, we will not do any assertion, just return 0 if mismatch with expectation
              if ast=1, we will throw assertion error immediately when status mismatch
    Mod     : self, calls the config_status command via jtag
    Require : only call this after verifying pin. There is one assumption that the pins are correct
    Output  : True if correct, False if incorrect
              Prints mismatching fields
    Note    : Checks all the status fields except 'ERROR_LOCATION', 'ERROR_DETAILS' (last 2)
    '''
    def verify_rsu_status(self, ast=0, rsu_state=1, check_version=0, fpga=False):
        if not fpga:
            cv_logger.info("V%d :: Verify rsu_status via JTAG" %(self._verify_counter))
            try:
                local_respond = self.jtag_send_sdmcmd(SDM_CMD['RSU_STATUS'])
            except:
                assert_err(0, "ERROR :: RSU_STATUS command failed")
        else:
            cv_logger.info("V%d :: Verify rsu_status via FPGA Mailbox IP" %(self._verify_counter))
            assert_err( self.fpga!=None, "ERROR :: You must get FPGA connector before can verify status thru fpga connector")
            try:
                self.fpga.write_command(SDM_CMD['RSU_STATUS'])
                local_respond = self.fpga_read_respond()
                cv_logger.info("Send CONFIG_STATUS :: Response %s" %str(local_respond))
            except:
                assert_err(0, "ERROR :: Failed to send RSU_STATUS command thru FPGA connector")

        cv_logger.info("Send RSU_STATUS :: Response %s" %str(local_respond))

        self._verify_counter = self._verify_counter + 1

        default_val   = 0xFEABDEAD

        #Dictionary holding the rsu_status
        rsu_status  = {
                           'CURRENT_IMAGE_0'    : default_val,
                           'CURRENT_IMAGE_1'    : default_val,
                           'LAST_FAIL_IMAGE_0'  : default_val,
                           'LAST_FAIL_IMAGE_1'  : default_val,
                           'STATE'              : default_val,
                           'VERSION'            : default_val,
                           'ERROR_LOCATION'     : default_val,
                           'ERROR_DETAILS'      : default_val
                        }

        #First Check the Length of List received
        local_lst_length = len(local_respond)
        local_pass = True
        err_msgs = []

        if rsu_state == 0:
            if local_lst_length != 1:
                local_pass = False
            else:
                cv_logger.info("Invalid RSU_status as expected")
        else:
            # local_extract_header = int(local_respond[0])

            # 'Header info gives Number of Elements*4096'
            # local_number_element = local_extract_header/4096

            # print_err(((local_lst_length-1) == local_number_element), "ERROR :: Expected Length as per header = %d, but receieved length = %d" %(local_number_element, (local_lst_length-1)))
            # cv_logger.info("Expected Length as per header = %d, but receieved length = %d" %(local_number_element, (local_lst_length-1)))

            #Extract the values and fill the local dictionary
            local_counter = 0
            for element in local_respond:

                if(local_counter == 1):
                    rsu_status['CURRENT_IMAGE_0']   = int(element)

                elif(local_counter == 2):
                    rsu_status['CURRENT_IMAGE_1']   = int(element)

                elif(local_counter == 3):
                    rsu_status['LAST_FAIL_IMAGE_0'] = int(element)

                elif(local_counter == 4):
                    rsu_status['LAST_FAIL_IMAGE_1'] = int(element)

                elif(local_counter == 5):
                    rsu_status['STATE']             = int(element)

                elif(local_counter == 6):
                    rsu_status['VERSION']           = int(element)

                elif(local_counter == 7):
                    rsu_status['ERROR_LOCATION']    = int(element)

                elif(local_counter == 8):
                    rsu_status['ERROR_DETAILS']     = int(element)

                local_counter = local_counter + 1

            cv_logger.info("rsu_status['CURRENT_IMAGE_0']    = 0x%08x" %rsu_status['CURRENT_IMAGE_0'])
            cv_logger.info("rsu_status['CURRENT_IMAGE_1']    = 0x%08x" %rsu_status['CURRENT_IMAGE_1'])
            cv_logger.info("rsu_status['LAST_FAIL_IMAGE_0']  = 0x%08x" %rsu_status['LAST_FAIL_IMAGE_0'])
            cv_logger.info("rsu_status['LAST_FAIL_IMAGE_1']  = 0x%08x" %rsu_status['LAST_FAIL_IMAGE_1'])
            cv_logger.info("rsu_status['STATE']              = 0x%x" %rsu_status['STATE'])
            cv_logger.info("rsu_status['VERSION']            = 0x%x" %rsu_status['VERSION'])
            cv_logger.info("rsu_status['ERROR_LOCATION']     = 0x%x" %rsu_status['ERROR_LOCATION'])
            cv_logger.info("rsu_status['ERROR_DETAILS']      = 0x%x" %rsu_status['ERROR_DETAILS'])

            cv_logger.info("Comparing rsu_status with expectation...")

            if(rsu_status['CURRENT_IMAGE_0'] != self.exp_rsu_status['CURRENT_IMAGE_0']):
                err_msgs.append("ERROR :: CURRENT_IMAGE_0 value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['CURRENT_IMAGE_0'], self.exp_rsu_status['CURRENT_IMAGE_0']))
                local_pass = False

            if(rsu_status['CURRENT_IMAGE_1'] != self.exp_rsu_status['CURRENT_IMAGE_1']):
                err_msgs.append("ERROR :: CURRENT_IMAGE_1 value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['CURRENT_IMAGE_1'], self.exp_rsu_status['CURRENT_IMAGE_1']))
                local_pass = False

            if(rsu_status['LAST_FAIL_IMAGE_0'] != self.exp_rsu_status['LAST_FAIL_IMAGE_0']):
                err_msgs.append("ERROR :: LAST_FAIL_IMAGE_0 value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['LAST_FAIL_IMAGE_0'], self.exp_rsu_status['LAST_FAIL_IMAGE_0']))
                local_pass = False

            if(rsu_status['LAST_FAIL_IMAGE_1'] != self.exp_rsu_status['LAST_FAIL_IMAGE_1']):
                err_msgs.append("ERROR :: LAST_FAIL_IMAGE_1 value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['LAST_FAIL_IMAGE_1'], self.exp_rsu_status['LAST_FAIL_IMAGE_1']))
                local_pass = False

            if (self.exp_rsu_status['STATE'] == 1):
                if(rsu_status['STATE'] == 0 ):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['STATE'], self.exp_rsu_status['STATE']))
                    local_pass = False
            else:
                if(rsu_status['STATE'] != self.exp_rsu_status['STATE']):
                    err_msgs.append("ERROR :: STATE value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['STATE'], self.exp_rsu_status['STATE']))
                    local_pass = False

            if(check_version):
                if(rsu_status['VERSION'] != self.exp_rsu_status['VERSION']):
                    err_msgs.append("ERROR :: VERSION value mismatched Measured = 0x%x and Expected = 0x%x" %(rsu_status['VERSION'], self.exp_rsu_status['VERSION']))
                    local_pass = False


        if err_msgs:
            for err in err_msgs:
                print_err(err)
            if ast:
                assert_err(0, "ERROR :: RSU_STATUS incorrect")
            else:
                print_err("ERROR :: RSU_STATUS incorrect")
        else:
            cv_logger.info("RSU_STATUS result same as expectation")
        return local_pass

    '''
    Modify  : Power up DUT, Reset CSR upon power up and Configure data prefetcher
    prov_fw -- it should be set if the RSU image is loaded after the provision firmware.
               This will add puf_data_0 (0x1F90) to the prefetcher list
    app_arr --  contains the array of fw_info dictionary (returned from the API - get_image_fw_add
    '''
    def rsu_set_prefetcher(self, dcmf=1, cpb=0, factory=0, app1=0, app2=0, app3=0, reconfig=0, prov_fw=0, extra=None, app_arr=None, puf_enable=0 ):
        #skip this step whenever running on mudv platform
        if self._sdmio.platform == 'mudv':
            cv_logger.info("Skip to rsu_set_prefetcher on mudv platform")
            return

        cv_logger.info("Set Prefetcher")

        # Define current acds version & build
        acds_version = os.environ.get("ACDS_VERSION")
        acds_build = float(os.environ.get("ACDS_BUILD_NUMBER"))

        assert_err(dcmf >=1 and dcmf<=4, "ERROR :: DCMF copy must be within 1-4, user set to %d" %dcmf )
        assert_err(cpb >=0 and cpb<=1, "ERROR :: CPB copy must be within 0-1, user set to %d" %cpb )
        # if (! hasattr(self, 'prefetcher_list')):
            # self.prefetcher_list = []
        if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
            prefetcher_list = [0x1BC]

        else:
            prefetcher_list = []


        # DCMF offset
        if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and "agilex" in self.DUT_FAMILY)!=True:
            if dcmf >= 1:
                prefetcher_list.append(0)
        if dcmf >= 2:
            prefetcher_list.append(self.DUT_FILTER.prefetcher_multiplier*256*1024)
        if dcmf >= 3:
            prefetcher_list.append(2*self.DUT_FILTER.prefetcher_multiplier*256*1024)
        if dcmf >= 4:
            prefetcher_list.append(3*self.DUT_FILTER.prefetcher_multiplier*256*1024)

        # if cpb >= 0:
        prefetcher_list.append(self.CPB0_START_ADD)
        # if cpb >= 1:
        prefetcher_list.append(self.CPB1_START_ADD)

        if (prov_fw == 1):
	        ' add the PUF address into the prefetcher list '
	        prefetcher_list.append(MAIN_IMAGE_POINTER['puf_data_0'][0])
	        prefetcher_list.append(MAIN_IMAGE_POINTER['puf_data_1'][0])

        if factory == 1:
            prefetcher_list.append(self.FACTORY_IMAGE_START_ADD)
            prefetcher_list.append(self.FACTORY["SSBL_START_ADD"]-0x1000) #obtained from map file values
            prefetcher_list.append(self.FACTORY["MAIN_START_ADD"][1])

            if ("agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if puf_enable == 1:
                    prefetcher_list.append(self.FACTORY["SSBL_START_ADD"])
                    prefetcher_list.append(0x350010)
                    prefetcher_list.append(0x348010)
                else:
                    prefetcher_list.append(self.FACTORY["SSBL_START_ADD"])

            if reconfig == 1:
                prefetcher_list.append(self.FACTORY["SSBL_END_ADD"])
            # if (! self.FACTORY_IMAGE_START_ADD in prefetcher_list):
            # prefetcher_list.append(self.factory["MAIN_ADD"][1])
        if app1 == 1:
            prefetcher_list.append(self.P1_START_ADD)
            prefetcher_list.append(self.P1["SSBL_START_ADD"]-0x1000)
            prefetcher_list.append(self.P1["MAIN_START_ADD"][1])
            if ("agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                prefetcher_list.append(self.P1["SSBL_START_ADD"])
            if reconfig == 1:
                prefetcher_list.append(self.P1["SSBL_END_ADD"])
            # prefetcher_list.append(self.P1["MAIN_ADD"][1])
        if app2 == 1:
            if (hasattr(self, 'P2_START_ADD')):
                prefetcher_list.append(self.P2_START_ADD)
                prefetcher_list.append(self.P2["SSBL_START_ADD"]-0x1000)
                prefetcher_list.append(self.P2["MAIN_START_ADD"][1])
                if ("agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                    prefetcher_list.append(self.P2["SSBL_START_ADD"])
                if reconfig == 1:
                    prefetcher_list.append(self.P2["SSBL_END_ADD"])
            # prefetcher_list.append(self.P2["MAIN_ADD"][1])
        if app3 == 1:
            if (hasattr(self, 'P3_START_ADD')):
                prefetcher_list.append(self.P3_START_ADD)
                prefetcher_list.append(self.P3["SSBL_START_ADD"]-0x1000)
                prefetcher_list.append(self.P3["MAIN_START_ADD"][1])
                if ("agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                    prefetcher_list.append(self.P3["SSBL_START_ADD"])
                if reconfig == 1:
                    prefetcher_list.append(self.P3["SSBL_END_ADD"])
            # prefetcher_list.append(self.P3["MAIN_ADD"][1])

        if((type(app_arr) != type([])) and (app_arr != None)):
            # covert it into an array
            app_arr = [app_arr]

        # process the dictionary array elements
        if((app_arr != None) and (type(app_arr) == type([])) and (len(app_arr) != 0)):
            ' For each of the "app_arr" element, containing the dictionary element of fw_info, returned by the API: get_image_fw_add '
            for count in range (0, len(app_arr)):
                #cv_logger.info("App[%d] Image Start: 0x%x" %(count, app_arr[count]['START_ADD']))
                prefetcher_list.append(app_arr[count]['START_ADD'])
                #cv_logger.info("App[%d] SSBL Start: 0x%x" %(count, app_arr[count]['SSBL_START_ADD'] - 0x1000))
                prefetcher_list.append(app_arr[count]["SSBL_START_ADD"]-0x1000)
                prefetcher_list.append(app_arr[count]["MAIN_START_ADD"][1])
                if ("agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                    prefetcher_list.append(app_arr[count]["SSBL_START_ADD"])

                if reconfig == 1:
                    cv_logger.info("App[%d] SSBL End: 0x%x" %(count, app_arr[count]['SSBL_END_ADD']))
                    prefetcher_list.append(app_arr[count]["SSBL_END_ADD"])

        # DCIO address
        prefetcher_list.append(0x100000*self.DUT_FILTER.prefetcher_multiplier)

        # To support rsu update new image offset/non-exist offset
        if extra != None:
            if isinstance(extra, list):
                prefetcher_list.extend(extra)
            else:
                prefetcher_list.append(extra)

        cv_logger.info("Prefetcher set: [{}]".format(', '.join(hex(x) for x in prefetcher_list)))
        # for Prefetcher in prefetcher_list:
            # cv_logger.info("Prefetcher set: 0x%x" %Prefetcher)
        # Configure data prefetcher
        self.qspi.set_prefetcher(*prefetcher_list)

    '''
    Modify  : different power up reset sequence in different platform
              - mudv   (with external flash daughter card)
              - oscar  (without daughter card)
    '''
    def power_up_reset(self,cmf_copy=1, puf_enable=0):
        if self._sdmio.platform in ['oscar', 'emulator', 'simics','oscarbb']:
            #self.power_up_reset_bfm(cmf_copy=cmf_copy, puf_enable=puf_enable)
            self.power_up_reset_bfm() #AR: Yan See will finalise the code
        elif self._sdmio.platform == 'mudv':
            super(RsuTest, self).power_up_reset()
        else:
            raise 'Unsupported Platform in QSPI'


    '''
    Modify  : Power up DUT, Reset CSR upon power up and Configure data prefetcher
    '''
    def power_up_reset_bfm(self):

        cv_logger.info("RSU power up reset")
        # Power up dut
        self.power.set_power(True)

        # Reset CSR upon power up
        cv_logger.info("Reset CSR upon power up")
        self.qspi.write_csr(True, False)
        self.verify_qspi_bfm_status()
        # [prefetcher_busy, bfm_status] = self.qspi.read_csr()
        # cv_logger.info("Prefetcher Busy = %d" % prefetcher_busy)
        # cv_logger.info("BFM status = %d" % bfm_status)
        # assert_err( bfm_status == 1,
            # "ERROR :: Unexpected QSPI BFM CSR status : %d" %bfm_status )


    '''
    Modify  : different prepare qspi sequence in different platform
              - mudv   (with external flash daughter card)
              - oscar  (without daughter card)
    '''
    def prepare_qspi_rsu(self, file_path=None, chip_select=0, bitstream=None, offset=0, verify=0, check_ram=1, ast=0, timeout=120, reverse=False, reconfig=0):
        if self._sdmio.platform in ['oscar', 'emulator', 'simics','oscarbb']:
            self.prepare_qspi_rsu_using_bfm(file_path, bitstream, offset=offset, check_ram=check_ram, ast=ast, timeout=timeout)
        elif self._sdmio.platform == 'mudv':
            cv_logger.info('Running on MUDV Platform')
            self.prepare_qspi_rsu_using_daughter_card(rpd=file_path, bitstream=bitstream, chip_select=chip_select, offset=offset, verify=verify, reverse=reverse, reconfig=reconfig)
        else:
            raise 'Unsupported Platform in Rsu'


    def prepare_qspi_rsu_using_daughter_card(self, rpd, bitstream, chip_select, offset, verify, reverse, reconfig):
        super(RsuTest, self).prepare_qspi(rpd, bitstream, chip_select=chip_select, offset=offset, verify=verify, reverse=reverse, reconfig=reconfig)
        return

    '''
    # Input   : file_path -- path for the bitstream file (usually rbf file)
                bitstream -- bitstream in LSB
                offset -- offset of RAM to write into
                ast -- 1 if ast for check_ram(), 0 otherwise
    # Optional: check_ram -- 1 if want to check the bitstream written into RAM, if not 0
    # Modify  : self, prepares QSPI configuration by writing bitstream into RAM
    # '''
    # def prepare_qspi(self, bitstream, offset=0, check_ram=1, ast=0, reverse=0):
    def prepare_qspi_rsu_using_bfm(self, file_path=None, bitstream=None, offset=0, check_ram=1, ast=0, timeout=120):
        if (bitstream==None):
            #read bitstream into byte array
            bitstream = self.read_bitstream(file_path)
            reverse = True
        else:
            reverse = False

        #prepare the RAM
        cv_logger.info("Writing Bistream into RAM for QSPI...")
        self.dut.test_time()
        self.qspi.prepare_data(bitstream, offset, reverse, timeout)
        cv_logger.info("Time to write data into RAM: %s" % self.dut.elapsed_time())
        #if user specified, check the RAM bistream
        if check_ram:
            self.check_ram(bitstream=bitstream, ast=ast)
        else:
            cv_logger.warning("QSPI RAM bitstream not checked")
            delay(1000)

        cv_logger.info("Finished preparing QSPI")

        # return len(bitstream)

    '''
    # Input   : file_path -- path for the bitstream file ( rpd file), map_file
    # Modify  : reads the bitstream given and initializes these variables:
    #           self.iid_puf_addr_map.PUF_OFFSET = []            #Offset location in MIP i.e. 1F90/1F98 for PUF Data
                self.iid_puf_addr_map.PUF_ADD = []               #Offset location for base of actual PUF data i.e. 100000/108000
                self.iid_puf_addr_map.HELP_DATA_OFFSET = []      #Offset location for help data offset i.e. 100008/108008
                self.iid_puf_addr_map.WKEY_DATA_OFFSET = []      #Offset location for wkey data offset i.e. 10000C/10800C
                self.iid_puf_addr_map.PUF_DATA_ADDR = []         #Offset location for actual PUF data i.e. 101000/109000
                self.iid_puf_addr_map.PUF_WKEY_ADDR = []         #Offset location for actual WKEY data i.e. 102000/110000
    # Output  : none
    '''
    def rpd_get_puf_add(self,file,map_file):

        self.iid_puf_addr_map = PufAdd()
        self.iid_puf_addr_map.BOOT_INFO_START_ADD = self.BOOT_INFO_START_ADD
        self.iid_puf_addr_map.puf_extract_addr_map(file, map_file)

    '''
    # Input   : file_path -- path for the bitstream file ( rpd file)
    # Modify  : reads the bitstream given and initializes these variables:
    #           self.BOOT_INFO_OFFSET
                self.NSLOTS
                self.CPB0_APP1_START
                self.CPB0_APP2_START
                self.CPB0_APP3_START
                The following are dict that contains    "MAIN_ADD", "MAIN_SEC_NUM"
                                                        "SSBL_START_ADD", "SSBL_END_ADD"
                                                        "TRAMPOLINE_START_ADD", "TRAMPOLINE_END_ADD"
                self.factory
                self.P1
                self.P2
                self.P3
    # Output  : returns full bitstream that reverted
    '''
    def rpd_get_rsu_fw_add(self,file):

        'get the base address of the ssbl descriptor reading the bitstream file'
        'Open the file'
        file_obj = open(file, "rb")
        assert_err( file_obj, "ERROR :: Failed to Open the file %s" %file)

        bitstream = bytearray(file_obj.read())
        file_obj.close()

        cv_logger.info("Reversing data (LSB <-> MSB) per BYTE ")
        for i in range(len(bitstream)) :
            data = bitstream[i]
            temp = 0
            for j in range(8) :
                if (data & (1 << j)) :
                    temp |= (1 << (7-j))
            bitstream[i] = temp

        # SPT_DESC = {
            # 'magic_word'        : [0x000, 4],
            # 'version'           : [0x004, 4],
            # 'entry_mum'         : [0x008, 4],
            # 'sp0_name'          : [0x020, 16],
            # 'sp0_offset'        : [0x030, 8],
            # 'sp0_length'        : [0x038, 4],
            # 'sp0_flags'         : [0x03C, 4],
        index_start = self.SPT0_START_ADD + SPT_DESC['sp0_offset'][0]
        index_end = index_start + SPT_DESC['sp0_offset'][1]
        # cv_logger.debug("0x%x 0x%x" %(index_start, index_end))
        self.BOOT_INFO_OFFSET = self.read_add(bitstream, index_start, index_end)
        cv_logger.info("BOOT_INFO_OFFSET: 0x%x" %self.BOOT_INFO_OFFSET )

        # CPB_DESC = {
            # 'magic_word'        : [0x000, 4],
            # 'cpb_header_size'   : [0x004, 4],
            # 'cpb_size'          : [0x008, 4],
            # 'iptab_offset'      : [0x010, 4],
            # 'iptab_nslots'      : [0x014, 4],
            # 'image1'            : [0x020, 8],
            # 'image2'            : [0x028, 8],
        index_start = self.CPB0_START_ADD + CPB_DESC['iptab_nslots'][0]
        index_end = index_start + CPB_DESC['iptab_nslots'][1]
        self.NSLOTS = self.read_add( bitstream, index_start, index_end)
        cv_logger.info("NSLOTS: 0x%x" %self.NSLOTS )

        if hasattr(self, 'P1_START_ADD'):
            index_start = self.CPB0_START_ADD + CPB_DESC['image1'][0]
            index_end = index_start + CPB_DESC['image1'][1]
            self.CPB0_APP1_START = self.read_add( bitstream, index_start, index_end)
            cv_logger.info("CPB0_APP1_START: 0x%x" %self.CPB0_APP1_START )

        if hasattr(self, 'P2_START_ADD'):
            index_start = self.CPB0_START_ADD + CPB_DESC['image2'][0]
            index_end = index_start + CPB_DESC['image2'][1]
            self.CPB0_APP2_START = self.read_add( bitstream, index_start, index_end)
            cv_logger.info("CPB0_APP2_START: 0x%x" %self.CPB0_APP2_START )

        if hasattr(self, 'P3_START_ADD'):
            index_start = self.CPB0_START_ADD + CPB_DESC['image3'][0]
            index_end = index_start + CPB_DESC['image3'][1]
            self.CPB0_APP3_START = self.read_add( bitstream, index_start, index_end)
            cv_logger.info("CPB0_APP3_START: 0x%x" %self.CPB0_APP3_START )

        self.FACTORY = self.get_image_fw_add( bitstream, self.FACTORY_IMAGE_START_ADD, "FACTORY")

        if hasattr(self, 'P1_START_ADD'):
           self.P1 = self.get_image_fw_add( bitstream, self.P1_START_ADD, "P1")

        if hasattr(self, 'P2_START_ADD'):
           self.P2 = self.get_image_fw_add( bitstream, self.P2_START_ADD, "P2")

        if hasattr(self, 'P3_START_ADD'):
           self.P3 = self.get_image_fw_add( bitstream, self.P3_START_ADD, "P3")
        
        if hasattr(self, 'P4_START_ADD'):
           self.P4 = self.get_image_fw_add( bitstream, self.P4_START_ADD, "P4")

        if hasattr(self, 'P5_START_ADD'):
           self.P5 = self.get_image_fw_add( bitstream, self.P5_START_ADD, "P5")

        # self.get_rsu_fw_add(bitstream)

        return bitstream