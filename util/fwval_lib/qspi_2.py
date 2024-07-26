'''
    Input   : bitstream -- the bitstream data
              ast -- 1 if assert, 0 otherwise
              random_check -- 1 if to randomly check the bitstream
    Modify  : self, prepares QSPI configuration by writing bitstream into RAM
    Output  : return 1 if good, 0 if bad
    '''
    def check_ram(self, bitstream=None, random_check=1, ast=1, file_path=None):

        if bitstream == None:
            if file_path == None:
                assert_err(0, "ERROR :: Cannot check ram for QSPI, please provide bitstream or file_path\n\n")
            else:
                #read bitstream into byte array
                bitstream = self.read_bitstream(file_path)

                cv_logger.info("Reversing data (LSB <-> MSB) per BYTE before checking RAM")
                for i in range(len(bitstream)) :
                    data = bitstream[i]
                    temp = 0
                    for j in range(8) :
                        if (data & (1 << j)) :
                            temp |= (1 << (7-j))
                    bitstream[i] = temp

        bitstream_length = len(bitstream)

        cv_logger.info("Checking RAM...")

        if (random_check):
            local_pass = True
            for i in range(16) :
                random.seed()
                addr = random.randint(0, bitstream_length-32)
                cv_logger.info("Randomly verify at address 0x%08X (32 Bytes)" % addr)
                data = self.qspi.read_back(addr, 32)
                for j in range(32) :
                    if (bitstream[addr + j] != data[j]):
                        local_pass = False
                        cv_logger.error("At offset %d: expected 0x%02X but found 0x%02X" % (j, bitstream[addr + j], data[j]))

        else:

            local_pass = True
            read_back_data=[]
            self.dut.test_time()
            read_back_data = self.qspi.read_back(0x0,bitstream_length)
            cv_logger.info("Time to read data from RAM: %s" % self.dut.elapsed_time())
            assert_err((not ast) or (len(read_back_data) == bitstream_length),
                "ERROR :: Readback RAM data length is %d, expected %d bytes"
                %(len(read_back_data), bitstream_length))

            if len(read_back_data) != bitstream_length:
                print_err("ERROR :: Readback RAM data length is %d, expected %d bytes"
                    %(len(read_back_data), bitstream_length))

            self.dut.test_time()
            for i in xrange(bitstream_length):
                if(bitstream[i]^read_back_data[i]):
                    local_pass = False
                    cv_logger.error("Expected data = 0x%x; read data = 0x%x; offset=%d" %(bitstream[i],read_back_data[i],i))
            cv_logger.info("Time to Compare content: %s" % self.dut.elapsed_time())

        assert_err(((not ast) or local_pass),
            "ERROR :: Readback RAM data is different than expected")

        if local_pass:
            cv_logger.info("Data written into RAM looks good")
        else:
            print_err("ERROR :: Readback RAM data is different than expected")
        return local_pass

    '''
    Require : expected QSPI RAM should be prepared beforehand
    Input   :
              success -- 1 if sending should success, 0 otherwise
              failed_cmf_state -- whther the device is in cmf_state after EXPECTED
                FAILED configuration. Device must currently be in bootrom stage
                and the cmf must not be loaded at the attempted configuration
              failed_state -- specific failed configuration state to match when configuration failed.
                Check only when success is 0,
                if not specified (default to 1), test just make sure state in CONFIG_STATUS returns non-zero.
              ast -- 0 if assertion disabled for status and pin check for this to happen
              timeout -- timeout for QSPI configuration, default 5s
              error_nstatus -- 0 nstatus remains 0 when go to error-idle state; 1 if nstatus will remains 1 when go to error-failack state
              skip_ver -- skip version check of the firmware
    Modify  : self, Change nconfig to 1, then make sure qspi configuration is happenned
              checks all results before and after configuration
    Output  : a list of True and False for pin and status checks
    '''
    def nconfig1_qspi(self, timeout=5, failed_cmf_state=2, success=1, error_nstatus=1, ast=0, failed_state=1, skip_ver=0):
        cv_logger.info("")
        local_success = []


        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            sampling_interval=30000
            # qspi typically requires 15 minutes or more to be configured
            if timeout < 15*60 :
                # let's make it 40 minutes by default to be sure
                cv_logger.info("overiding timeout of %ds to %ds" % (timeout, timeout*8*60))
                timeout = timeout*8*60
        else:
            sampling_interval=500

        # Drive nconfig => 1
        cv_logger.info("Setting nCONFIG => 1")
        self.update_exp(nconfig=1, nstatus=1)
        self.nconfig.set_input(1)

        # # Check pin
        self.dut.test_time()
        self._lib_delay()
        cur_delay = 1000
        self.update_exp(config_done=1, init_done=1)
        pin_result_temp = self.verify_pin(ast=ast,log_error=0)
        cv_logger.info("pin_result_temp: %s" % pin_result_temp)
        limit_timeout = timeout * 1000 # Change to miliseconds

        if os.environ.get("PYCV_PLATFORM") == 'simics' :
            # This should be the way for all platform, tweaking timing wont last
            # And why the Test do not use the platform information from the dut?!?!?!
            # And need to use env setting
            self.qspi.config_inactive()

        while ((pin_result_temp == False) & (cur_delay < limit_timeout) ):
            cv_logger.info("Pin mismatch - conf_done is still low?")
            cur_delay += sampling_interval
            cv_logger.info("total delay: %d ms" %cur_delay )
            delay(sampling_interval, self.dut)
            pin_result_temp = self.verify_pin(ast=ast,log_error=0)

        cv_logger.info("Checking pin and status after attempted QSPI configuration")
        if(success):

            if (pin_result_temp == False):
                cv_logger.debug("Timeout after %s" % self.dut.elapsed_time())
            else:
                cv_logger.info("Time to get nstatus and conf_done high: %s" % self.dut.elapsed_time())
            # local_success.append(pin_result_temp)

            
            # [prefetcher_busy, bfm_status] = self.qspi.read_csr()
            # cv_logger.info("BFM status = %d" % bfm_status)
            # assert_err( bfm_status == 1,
                # "ERROR :: Unexpected QSPI BFM CSR status : %d" %bfm_status )

            #update expectations
            self.update_exp(state=0x0, config_done=1, init_done=1)
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
                fwval.delay(10000)
            #check pins and config_status
            local_success.append(self.verify_pin(ast=ast))
            local_success.append(self.verify_status(cmf_state=1, ast=ast, skip_ver=skip_ver))
            if False in local_success:
                # Check QSPI BFM CSR status
                # only check qspi bfm status if configuration is failed. refer to 15011347718
                self.verify_qspi_bfm_status()

            # assert_err( config_status == 1,
            # "ERROR :: Unexpected config status" )

        else:
            if (pin_result_temp == 0):
                cv_logger.info("(Expected) Timeout: %s" % self.dut.elapsed_time() )
            else:
                cv_logger.info("Time to get nstatus and conf_done high: %s" % self.dut.elapsed_time())
                assert_err( not ast,
                    "ERROR :: Unexpected pin result with corrupted bitstream")

            self.update_exp(config_done=0, init_done=0)
            if (failed_cmf_state == 1):
                self.update_exp(state=failed_state)
                if (error_nstatus == 0):
                    self.update_exp(nstatus=0)
            # elif (failed_cmf_state == 0):
                # self.update_exp(nstatus=1)

            #check pins and config_status
            local_success.append(self.verify_pin(ast=ast))
            local_success.append(self.verify_status(cmf_state=failed_cmf_state, ast=ast, skip_ver=skip_ver))
            # assert_err( config_status == 1,
                # "ERROR :: Unexpected config status" )

        cv_logger.info("Finished nconfig1_qspi")

        if os.environ.get('FWVAL_PLATFORM') == "emulator" :
            wait_time = 130
            cv_logger.info("Wait for %ds" % wait_time)
            delay(wait_time*1000)

        return local_success


    '''
    Require : expected QSPI RAM should be prepared beforehand
    Input   :
              success -- 1 if sending should success, 0 otherwise
              failed_cmf_state -- whther the device is in cmf_state after EXPECTED
                FAILED configuration. Device must currently be in bootrom stage
                and the cmf must not be loaded at the attempted configuration
              failed_state -- specific failed configuration state to match when configuration failed.
                Check only when success is 0,
                if not specified (default to 1), test just make sure state in CONFIG_STATUS returns non-zero.
              ast -- 0 if assertion disabled for status and pin check for this to happen
              timeout -- timeout for QSPI configuration, default 5s
              skip -- 1 if want to skip checking the device status after drive nconfig to 0
              skip_ver -- skip version check of the firmware
    Modify  : self, Change nconfig to 1, then make sure qspi configuration is happenned
              checks all results before and after configuration
    Output  : a list of True and False for pin and status checks
    '''
    def toggle_nconfig_qspi(self, timeout=5, chk_config_status=False, failed_cmf_state=2, success=1, error_nstatus=1, ast=0, skip=1, skip_ver=0, failed_state=1):
        cv_logger.info("")
        local_success = []
        cv_logger.info("Toggle nconfig and expected configuration via QSPI")

        # Drive nconfig => 0
        cv_logger.info("Setting nCONFIG => 0")
        self.update_exp(nconfig=0, nstatus=0, config_done=0, init_done=0)
        self.nconfig.set_input(0)
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            cv_logger.debug(":Delay 250s for emulator")
            fwval.delay(250000)
        else:
            self.dut.delay(2000)
        local_success.append(self.verify_pin(ast=ast,wait_time_out_check=True))
        cv_logger.debug("Adding more delay post nCONFIG-->0 to check it it is really effective causing to stay in bootrom.........")
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            fwval.delay(150000)
        else:
            delay(1000, self.dut)

        #-------Added by SatyaS to check the bootrom status-----------------#
        local_respond = self.jtag_send_sdmcmd(SDM_CMD['CONFIG_STATUS'])
        cv_logger.info("Send CONFIG_STATUS :: Response %s" %str(local_respond))
        local_lst_length = len(local_respond)

        if(chk_config_status):
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(local_lst_length == 4):
                    cv_logger.debug("Interruption occured in bootrom stage  <> OK")
                else:
                    local_success.append(False)
                    cv_logger.error("Interruption did not occured in bootrom stage  <> KO")
            else:
                if(local_lst_length == 2):
                    cv_logger.debug("Interruption occured in bootrom stage  <> OK")
                else:
                    local_success.append(False)
                    cv_logger.error("Interruption did not occured in bootrom stage  <> KO")


        # [prefetcher_busy, bfm_status] = self.qspi.read_csr()
        # cv_logger.info("BFM status = %d" % bfm_status)
        if (not skip):
            self.debug_read_bootstatus()

        if os.environ.get("PYCV_PLATFORM") != 'simics' :
            [design_hash_return, sld_node_return] = self.check_idle_jtagconfig()
            assert_err( not design_hash_return and not sld_node_return,
                "ERROR :: Device should not be in user-mode")

        # Drive nconfig => 1 and check result
        local_success.extend(self.nconfig1_qspi( timeout=timeout, failed_cmf_state=failed_cmf_state, success=success, error_nstatus=error_nstatus, ast=ast, failed_state=failed_state,skip_ver=skip_ver))

        if False in local_success:
                # Check QSPI BFM CSR status
                # only check qspi bfm status if configuration is failed. refer to 15011347718
                self.verify_qspi_bfm_status()

        cv_logger.info("Finished toggle_nconfig_qspi")
        return local_success


    '''
    Require : Reconfiguration via QSPI including prepare QSPI into RAM first
    Input   : file_path -- path for the bitstream file (rpd file)
              success -- 1 if sending should success, 0 otherwise
              failed_state -- specific failed configuration state to match when configuration failed.
                Check only when success is 0,
                if not specified (default to 1), test just make sure state in CONFIG_STATUS returns non-zero.
              offset -- byte offset to start sending bitstream, defualt 0
              check_ram -- 1 if want to check the bitstream written into RAM, if not 0
              failed_cmf_state -- whther the device is in cmf_state after EXPECTED
                FAILED configuration. Device must currently be in bootrom stage
                and the cmf must not be loaded at the attempted configuration
              ast -- 0 if assertion disabled for status and pin check for this to happen
              timeout -- timeout for QSPI configuration, default 5s
              skip_ver -- skip version check of the firmware
    Modify  : self, Change nconfig to 1, then make sure qspi configuration is happenned
              checks all results before and after configuration
    Output  : a list of True and False for pin and status checks
    '''
    def reconfig_qspi(self, file_path=None, timeout=5, offset=0, failed_cmf_state=2, check_ram=1, success=1, error_nstatus=1, ast=0, failed_state=1, send_efuse_write_disable=1, reconfig=1, skip_ver=0, skip_extract=0):
        cv_logger.info("")
        local_success = []
        cv_logger.info("Reconfiguration via QSPI, download flash with %s" %file_path)

        # Download data to QSPI BFM
        self.prepare_qspi( file_path=file_path, offset=offset, check_ram=check_ram, ast=ast, reconfig=reconfig, skip_extract=skip_extract)

        # Define current acds version & build
        acds_version = os.environ.get("ACDS_VERSION")
        acds_build = float(os.environ.get("ACDS_BUILD_NUMBER"))

        if not self.daughter_card:
            # Re-configure prefetcher
            ssbl_add1 = self.SSBL_START_ADD
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x,  0x%x,  0x%x" % (ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000)
                else:
                    cv_logger.info("QSPI set prefetcher 0x0, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x,  0x%x,  0x%x" % (ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000))
                    self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000)
            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x,  0x%x,  0x%x" % (ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000,ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000)
                else:
                    cv_logger.info("QSPI set prefetcher 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x,  0x%x,  0x%x" % (ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000,ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000)

        # Toggle nconfig and check result
        local_success.extend( self.toggle_nconfig_qspi(timeout=timeout, failed_cmf_state=failed_cmf_state, success=success, error_nstatus=error_nstatus, ast=ast, failed_state=failed_state,skip_ver=skip_ver ))

        # Send efuse_write_disable command again after reconfiguration to make sure the sdm command is set
        if (self._fuse_write_disabled) and (send_efuse_write_disable):
            cv_logger.info("Send EFUSE_WRITE_DISABLE command again after reconfiguration to make sure it is SET")
            self.efuse_write_disable(skip_program=False)

        # Verify design
        if(success):
            self.verify_design(design_name=file_path)

        return local_success

    '''
    Input    : design_name -- as long as design_name contains "and"/"or" (case insensitive), this function will verify whether
               the programmed device has the correct design
    '''
    def verify_design(self, design_name, ast=1):
        local_pass = self.verify_design_andor(design_name, ast=ast)
        return local_pass


    '''
    Require : Using test firmware
    Input    : freq -- as clock freq
    '''
    def verify_asclock(self, freq):
        cv_logger.info("Verify BAUDDIV")

        try:
            baud = self.sdm.read("nios2r2", 0xb0002000, 1)
            cv_logger.info("Baud: 0x%x" %baud)
            if (baud == 0x80180001):
                bauddiv = "BAUD8"
            elif (baud == 0x80100001 ):
                bauddiv = "BAUD6"
            elif (baud == 0x80080001 ):
                bauddiv = "BAUD4"
            else:
                bauddiv = "Unknown"
            cv_logger.debug("bauddiv: %s"%bauddiv)

            if ( (freq == 58) & (bauddiv == "BAUD8") ) | ((freq == 77) & (bauddiv == "BAUD6")) | ((freq == 115) & (bauddiv == "BAUD4")):
                cv_logger.info("Matched bauddiv - Freq set: %d bauddiv: %s" %(freq, bauddiv))
            else:
                print_err("ERROR :: bauddiv mismatched - Freq set: %s bauddiv: %s" %(freq, bauddiv))

            if ( self.sdm.read("nios2r2", 0x40000024, 1) == 0x04000000 ):
                cv_logger.info("0x40000024: 0x04000000")
            else:
                print_err("INFO :: 0x40000024: 0x%x"%(self.sdm.read("nios2r2", 0x40000024, 1)))

            if ( self.sdm.read("nios2r2", 0x40000028, 1) == 0x05000000 ):
                cv_logger.info("0x40000028: 0x05000000")
            else:
                print_err("INFO :: 0x40000028: 0x%x"%(self.sdm.read("nios2r2", 0x40000028, 1)))

            if ( self.sdm.read("nios2r2", 0x4000000c, 1) == 0x000001ef ):
                cv_logger.info("0x4000000c : 0x000001ef")
            else:
                print_err("INFO :: 0x4000000c : 0x%x"%(self.sdm.read("nios2r2", 0x4000000c , 1)))

            if ( self.sdm.read("nios2r2", 0x40000034 , 1) == 0x00020000 ):
                cv_logger.info("0x40000034  : 0x00020000")
            else:
                print_err("INFO :: 0x40000034  : 0x%x"%(self.sdm.read("nios2r2", 0x40000034  , 1)))
        except:
            cv_logger.warning("test failed to verify freq. Mainly because not using test firmware")

    '''
    # Input   : file_path -- path for the bitstream file ( map file)
    # Modify  : reads the bitstream given and initializes these variables:
                self.MBR_START_ADD        --  MBR start address
                self.MBR_END_ADD          --  MBR end address
                self.A2_PARTITION_START_ADD     -- A2_PARTITION start address
                self.A2_PARTITION_END_ADD       -- A2_PARTITION end addressx
                self.BOOT_INFO_START_ADD        -- 1st DCMF start address
                self.BOOT_INFO_END_ADD          -- 1st DCMF end address
                self.FACTORY_IMAGE_START_ADD    -- Factory image start address
                self.FACTORY_IMAGE_END_ADD      -- Factory image end address
                self.SPT0_START_ADD             -- SPT0 start address
                self.SPT0_END_ADD               -- SPT0 end address
                self.SPT1_START_ADD             -- SPT1 start address
                self.SPT1_END_ADD               -- SPT1 end address
                self.CPB0_START_ADD             -- CPB0 start address
                self.CPB0_END_ADD               -- CPB0 end address
                self.CPB1_START_ADD             -- CPB1 start address
                self.CPB1_END_ADD               -- CPB1 end address
                self.P1_START_ADD               -- P1 start address
                self.P1_END_ADD                 -- P1 end address
                self.P2_START_ADD               -- P2 start address
                self.P2_END_ADD                 -- P2 end address
                self.P3_START_ADD               -- P3 start address
                self.P3_END_ADD                 -- P3 end address
                self.PUF_START_ADD              -- PUF start address
                self.PUF_END_ADD                -- PUF end address
                self.PARTITION_48_START_ADD     -- PARTITION_48 start address
                self.PARTITION_48_END_ADD       -- PARTITION_48 end address
                self.PARTITION_A3_START_ADD     -- PARTITION_A3 start address
                self.PARTITION_A3_END_ADD       -- PARTITION_A3 end address
    # '''
    def map_get_rsu_add(self,file):
        'get the base address of the ssbl descriptor reading the bitstream file'
        'Open the file'
        file_obj = open(file, "rb")
        assert_err( file_obj, "ERROR :: Failed to Open the file %s" %file)
        content = file_obj.read().splitlines()
        file_obj.close()
        self.A2_PARTITION_START_ADD = 0

        for i in range(len(content)) :
            # python 3 will return bytes instead of string   
            if isinstance(content[i],bytes):
                content[i] = content[i].decode()
            searchObj = re.search( r'MBR\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.MBR_START_ADD = int(searchObj.group(1),0)
                self.MBR_INFO_END_ADD = int(searchObj.group(2),0)

            searchObj = re.search( r'PARTITION_A2 \(CONFIG\)\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.A2_PARTITION_START_ADD = int(searchObj.group(1),0)
                self.A2_PARTITION_END_ADD = int(searchObj.group(2),0)

            searchObj = re.search( r'BOOT_INFO\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.BOOT_INFO_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.BOOT_INFO_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'FACTORY_IMAGE\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.FACTORY_IMAGE_START_ADD = int(searchObj.group(1),0)+ self.A2_PARTITION_START_ADD
                self.FACTORY_IMAGE_END_ADD = int(searchObj.group(2),0)+ self.A2_PARTITION_START_ADD

            searchObj = re.search( r'SPT0\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.SPT0_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.SPT0_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'SPT1\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.SPT1_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.SPT1_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'CPB0\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.CPB0_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.CPB0_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'CPB1\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.CPB1_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.CPB1_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'P1\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.P1_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.P1_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'P2\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.P2_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.P2_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'P3\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.P3_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.P3_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'P4\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.P4_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.P4_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'P5\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.P5_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.P5_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'PUF\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.PUF_START_ADD = int(searchObj.group(1),0) + self.A2_PARTITION_START_ADD
                self.PUF_END_ADD = int(searchObj.group(2),0) + self.A2_PARTITION_START_ADD

            searchObj = re.search( r'PARTITION_48 \(LITTLEFS\)\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.PARTITION_48_START_ADD = int(searchObj.group(1),0)
                self.PARTITION_48_END_ADD = int(searchObj.group(2),0)

            searchObj = re.search( r'PARTITION_A3 \(BACKUP\)\s+(\w+)\s+(\w+)', content[i])
            if searchObj:
                self.PARTITION_A3_START_ADD = int(searchObj.group(1),0)
                self.PARTITION_A3_END_ADD = int(searchObj.group(2),0)

        if hasattr(self, 'MBR_START_ADD'):
            cv_logger.info("MBR_START_ADD : 0x%x" %self.MBR_START_ADD)
            cv_logger.info("MBR_END_ADD : 0x%x" %self.MBR_INFO_END_ADD)
        if hasattr(self, 'A2_PARTITION_START_ADD') and hasattr(self, 'A2_PARTITION_END_ADD'):
            cv_logger.info("A2_PARTITION_START_ADD : 0x%x" %self.A2_PARTITION_START_ADD)
            cv_logger.info("A2_PARTITION_END_ADD : 0x%x" %self.A2_PARTITION_END_ADD)
        if hasattr(self, 'BOOT_INFO_START_ADD') and hasattr(self, 'BOOT_INFO_END_ADD'):    
            cv_logger.info("BOOT_INFO_START_ADD : 0x%x" %self.BOOT_INFO_START_ADD)
            cv_logger.info("BOOT_INFO_END_ADD : 0x%x" %self.BOOT_INFO_END_ADD)
        if hasattr(self, 'FACTORY_IMAGE_START_ADD'):
            cv_logger.info("FACTORY_IMAGE_START_ADD : 0x%x" %self.FACTORY_IMAGE_START_ADD)
            cv_logger.info("FACTORY_IMAGE_END_ADD : 0x%x" %self.FACTORY_IMAGE_END_ADD)
        if hasattr(self, 'SPT0_START_ADD'):
            cv_logger.info("SPT0_START_ADD : 0x%x" %self.SPT0_START_ADD)
            cv_logger.info("SPT0_END_ADD : 0x%x" %self.SPT0_END_ADD)
        if hasattr(self, 'SPT1_START_ADD'):
            cv_logger.info("SPT1_START_ADD : 0x%x" %self.SPT1_START_ADD)
            cv_logger.info("SPT1_END_ADD : 0x%x" %self.SPT1_END_ADD)
        if hasattr(self, 'CPB0_START_ADD'):
            cv_logger.info("CPB0_START_ADD : 0x%x" %self.CPB0_START_ADD)
            cv_logger.info("CPB0_END_ADD : 0x%x" %self.CPB0_END_ADD)
        if hasattr(self, 'CPB1_START_ADD'):
            cv_logger.info("CPB1_START_ADD : 0x%x" %self.CPB1_START_ADD)
            cv_logger.info("CPB1_END_ADD : 0x%x" %self.CPB1_END_ADD)
        if hasattr(self, 'P1_START_ADD'):
            cv_logger.info("P1_START_ADD : 0x%x" %self.P1_START_ADD)
            cv_logger.info("P1_END_ADD : 0x%x" %self.P1_END_ADD)
        if hasattr(self, 'P2_START_ADD'):
            cv_logger.info("P2_START_ADD : 0x%x" %self.P2_START_ADD)
            cv_logger.info("P2_END_ADD : 0x%x" %self.P2_END_ADD)
        if hasattr(self, 'P3_START_ADD'):
            cv_logger.info("P3_START_ADD : 0x%x" %self.P3_START_ADD)
            cv_logger.info("P3_END_ADD : 0x%x" %self.P3_END_ADD)
        if hasattr(self, 'P4_START_ADD'):
            cv_logger.info("P4_START_ADD : 0x%x" %self.P4_START_ADD)
            cv_logger.info("P4_END_ADD : 0x%x" %self.P4_END_ADD)
        if hasattr(self, 'P5_START_ADD'):
            cv_logger.info("P5_START_ADD : 0x%x" %self.P5_START_ADD)
            cv_logger.info("P5_END_ADD : 0x%x" %self.P5_END_ADD)
        if hasattr(self, 'PUF_START_ADD'):
            cv_logger.info("PUF_START_ADD : 0x%x" %self.PUF_START_ADD)
            cv_logger.info("PUF_END_ADD : 0x%x" %self.PUF_END_ADD)
        if hasattr(self, 'PARTITION_48_START_ADD'):
            cv_logger.info("PARTITION_48_START_ADD : 0x%x" %self.PARTITION_48_START_ADD)
            cv_logger.info("PARTITION_48_END_ADD : 0x%x" %self.PARTITION_48_END_ADD)
        if hasattr(self, 'PARTITION_48_START_ADD'):
            cv_logger.info("PARTITION_A3_START_ADD : 0x%x" %self.PARTITION_A3_START_ADD)
            cv_logger.info("PARTITION_A3_END_ADD : 0x%x" %self.PARTITION_A3_END_ADD)


    '''
    *********************************************************************************************
    Output :: This method will read RPD file, reverse data and get SSBL's and trampoline's start and end address
    Modify -- puf_enable :: To enable puf address obtention (QSPI)
    *********************************************************************************************
    '''
    def rpd_get_fw_add(self,file, get_fw_add=1, puf_enable=0):

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
            
        # Pre-check for A2 startaddr. If A2 is not found, set a2__startaddr as 0
        a2__startaddr = 0
        if hasattr(self, 'A2_PARTITION_START_ADD'):
            a2__startaddr = self.A2_PARTITION_START_ADD

        if get_fw_add:
            self.get_fw_add(bitstream, puf_enable=puf_enable,a2_startaddr=a2__startaddr)

        return bitstream


    '''
    *********************************************************************************************
    Input   : bitstream --  bytearray of the bitstream read
    Output  : This method will read RPD file, reverse data and get SSBL start address
    *********************************************************************************************
    '''
    def rpd_get_ssbl_add(self,bitstream):
        cv_logger.info("Read SSBL start address")
        bitstream_temp = bytearray(bitstream)

        # offset for SSBL start add
        index_start     = BOOTROM_DESCRIPTOR['ssbl_offset'][0]
        index_end       = index_start + BOOTROM_DESCRIPTOR['ssbl_offset'][1]

        # cv_logger.info("Reversing SSBL start offset data (LSB <-> MSB) per BYTE ")
        for i in range(index_start,index_end) :
            data = bitstream_temp[i]
            temp = 0
            for j in range(8) :
                if (data & (1 << j)) :
                    temp |= (1 << (7-j))
            bitstream_temp[i] = temp

        src_buff        = bitstream_temp[index_start:index_end]
        src_buff_le     = reverse_arr(src_buff)
        add = int(binascii.hexlify(src_buff_le),16)
        cv_logger.info("%s_START_ADD: 0x%08x"% (self.SSBL_TSBL,add))
        self.SSBL_START_ADD = add

    '''
    *********************************************************************************************
    Input   : bitstream --  bytearray of the bitstream read
    Output  : This method will read RPD file, reverse data and get Trampoline start and end address
    *********************************************************************************************
    '''
    def rpd_get_trampoline_add(self,bitstream):
        cv_logger.info("Read Trampoline address")
        bitstream_temp = bytearray(bitstream)

        # Trampoline start add
        index_start     = CMF_DESCRIPTOR['offset_trampol'][0]
        index_end       = index_start + CMF_DESCRIPTOR['offset_trampol'][1]

        # cv_logger.info("Reversing Trampoline start offset data (LSB <-> MSB) per BYTE ")
        for i in range(index_start,index_end) :
            data = bitstream_temp[i]
            temp = 0
            for j in range(8) :
                if (data & (1 << j)) :
                    temp |= (1 << (7-j))
            bitstream_temp[i] = temp

        src_buff        = bitstream_temp[index_start:index_end]
        src_buff_le     = reverse_arr(src_buff)
        add = int(binascii.hexlify(src_buff_le),16)
        cv_logger.info("TRAMPOLINE_START_ADD: 0x%08x"% add)
        self.TRAMPOLINE_START_ADD = add

        # Trampoline end address
        index_start     = CMF_DESCRIPTOR['size_trampoline'][0]
        index_end       = index_start + CMF_DESCRIPTOR['size_trampoline'][1]

        # cv_logger.info("Reversing Trampoline start offset data (LSB <-> MSB) per BYTE ")
        for i in range(index_start,index_end) :
            data = bitstream_temp[i]
            temp = 0
            for j in range(8) :
                if (data & (1 << j)) :
                    temp |= (1 << (7-j))
            bitstream_temp[i] = temp

        src_buff        = bitstream_temp[index_start:index_end]
        src_buff_le     = reverse_arr(src_buff)
        add = int(binascii.hexlify(src_buff_le),16)
        cv_logger.info("TRAMPOLINE_END_ADD: 0x%08x"% add)
        self.TRAMPOLINE_END_ADD = add
