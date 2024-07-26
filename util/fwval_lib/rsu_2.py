'''
    Input   : bitstream --  bytearray of the bitstream read
                bitstream_start -- bitstream offset within the "bitstream"
                    If the image contains 2 Apps (P1 and P2), then the information needs to be
                    extracted for P1, then give the bitstream_start address as offset of P1 image
                    If an RSU update image is to be processed, then give this address as "0"
                image -- image name to printout in INFO
                single_image_rpd  -- default 0 for rpd file with RSU; 1 for single image rpd for RSU
                bitstream_flash_offset -- offset of the "bitstream" wherein the image will be stored in QSPI
    Output  : dict with the keys below:
              MAIN_START_ADD -- a list of main section start addresses
              MAIN_END_ADD -- a list of main section end addresses
              MAIN_SEC_NUM -- number of main sections
              SSBL_START_ADD -- start address of ssbl
              SSBL_END_ADD -- last address of ssbl
              TRAMPOLINE_START_ADD -- start address of trampoline
              TRAMPOLINE_END_ADD -- last address of trampoline
              SYNC_START_ADD -- start address of sync
              SYNC_END_ADD -- last address of sync
    '''
    def get_image_fw_add(self, bitstream, bitstream_start, image="Unkwown", single_image_rpd=0, single_image_offset=None, bitstream_flash_offset=0):

        cv_logger.info("Get FW INFO from %s" %image)

        fw_info = dict.fromkeys(["START_ADD","ABSOLUTE_START_ADD", "END_ADD", "MAIN_START_ADD", "MAIN_END_ADD", "MAIN_SEC_NUM", "SSBL_START_ADD", "SSBL_END_ADD", "TRAMPOLINE_START_ADD", "TRAMPOLINE_END_ADD" ,"SYNC_START_ADD", "SYNC_END_ADD"])

        index_offset    = 0
        index_size      = 1

        cv_logger.info("Bitstream processing to get address")
        fw_info["START_ADD"] = bitstream_start + bitstream_flash_offset - self.A2_PARTITION_START_ADD
        cv_logger.info("START_ADD: 0x%x"% fw_info["START_ADD"])

        fw_info["ABSOLUTE_START_ADD"] = bitstream_start + bitstream_flash_offset
        cv_logger.info("ABSOLUTE_START_ADD: 0x%x"% fw_info["ABSOLUTE_START_ADD"])

        # Main Image Pointer - last 256 bytes  of the second 4kB block within the firmware section
        index_start     = bitstream_start + MAIN_IMAGE_POINTER['sec_num'][index_offset]
        index_end       = index_start + MAIN_IMAGE_POINTER['sec_num'][index_size]
        fw_info["MAIN_SEC_NUM"] = self.read_add( bitstream, index_start, index_end)
        cv_logger.info("Main Image Pointer MAIN_SEC_NUM: %d"% fw_info["MAIN_SEC_NUM"])

        fw_info["MAIN_START_ADD"] = []
        fw_info["MAIN_END_ADD"] = []

        # dummy add 0
        fw_info["MAIN_START_ADD"].append(0)
        fw_info["MAIN_END_ADD"].append(0)

        main_sec = 1
        if fw_info["MAIN_SEC_NUM"] >= 1 :
            index_start     = bitstream_start + MAIN_IMAGE_POINTER['1st_main_add'][index_offset]
            index_end       = index_start + MAIN_IMAGE_POINTER['1st_main_add'][index_size]
            add = self.read_add( bitstream, index_start, index_end)
            #assert_err ( add != 0, "ERROR :: 1st main address cannot be 0")
            # if address == 0, it means we are using relative address
            if add == 0:
                index_start     = bitstream_start + CMF_DESCRIPTOR['fw_sec_size'][index_offset]
                index_end       = index_start + CMF_DESCRIPTOR['fw_sec_size'][index_size]
                add = bitstream_start + self.read_add( bitstream, index_start, index_end)
            cv_logger.info("MIP MAIN_START_ADD[%d]: 0x%08x"% (main_sec, add))
            fw_info["MAIN_START_ADD"].append(add)

            if (single_image_rpd == 0):
                # MAIN_END_ADD
                index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                add2 = add + self.read_add(bitstream, index_start, index_end) -1
                cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                fw_info["MAIN_END_ADD"].append(add2)
            else:
                if single_image_offset != None:
                    # MAIN_END_ADD
                    index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset] - single_image_offset
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add2 = add + self.read_add(bitstream, index_start, index_end) -1
                    cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                    fw_info["MAIN_END_ADD"].append(add2)

        if fw_info["MAIN_SEC_NUM"] >= 2 :
            index_start     = bitstream_start + MAIN_IMAGE_POINTER['2nd_main_add'][index_offset]
            index_end       = index_start + MAIN_IMAGE_POINTER['2nd_main_add'][index_size]
            add = self.read_add( bitstream, index_start, index_end)
            if add == 0:
                add = fw_info["MAIN_END_ADD"][1] + 1
            main_sec += 1
            cv_logger.info("MIP MAIN_START_ADD[%d]: 0x%08x"% (main_sec, add))
            fw_info["MAIN_START_ADD"].append(add)

            if (single_image_rpd == 0):
                # MAIN_END_ADD
                index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                add2 = add + self.read_add(bitstream, index_start, index_end) -1
                cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                fw_info["MAIN_END_ADD"].append(add2)
            else:
                if single_image_offset != None:
                    # MAIN_END_ADD
                    index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset] - single_image_offset
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add2 = add + self.read_add(bitstream, index_start, index_end) -1
                    cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                    fw_info["MAIN_END_ADD"].append(add2)

        if fw_info["MAIN_SEC_NUM"] >= 3 :
            index_start     = bitstream_start + MAIN_IMAGE_POINTER['3rd_main_add'][index_offset]
            index_end       = index_start + MAIN_IMAGE_POINTER['3rd_main_add'][index_size]
            add = self.read_add( bitstream, index_start, index_end)
            if add == 0:
                add = fw_info["MAIN_END_ADD"][2] + 1
            main_sec += 1
            cv_logger.info("MIP MAIN_START_ADD[%d]: 0x%08x"% (main_sec, add))
            fw_info["MAIN_START_ADD"].append(add)

            if (single_image_rpd == 0):
                # MAIN_END_ADD
                index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                add2 = add + self.read_add(bitstream, index_start, index_end) -1
                cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                fw_info["MAIN_END_ADD"].append(add2)
            else:
                if single_image_offset != None:
                    # MAIN_END_ADD
                    index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset] - single_image_offset
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add2 = add + self.read_add(bitstream, index_start, index_end) -1
                    cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                    fw_info["MAIN_END_ADD"].append(add2)

        if fw_info["MAIN_SEC_NUM"] >= 4 :
            index_start     = bitstream_start + MAIN_IMAGE_POINTER['4th_main_add'][index_offset]
            index_end       = index_start + MAIN_IMAGE_POINTER['4th_main_add'][index_size]
            add = self.read_add( bitstream, index_start, index_end)
            if add == 0:
                add = fw_info["MAIN_END_ADD"][3] + 1
            main_sec += 1
            cv_logger.info("MIP MAIN_START_ADD[%d]: 0x%08x"% (main_sec, add))
            fw_info["MAIN_START_ADD"].append(add)

            if (single_image_rpd == 0):
                # MAIN_END_ADD
                index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset]
                index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                add2 = add + self.read_add(bitstream, index_start, index_end) -1
                cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                fw_info["MAIN_END_ADD"].append(add2)
            else:
                if single_image_offset != None:
                    # MAIN_END_ADD
                    index_start = add + MAIN_DESCRIPTOR['size_main_sec'][index_offset] - single_image_offset
                    index_end   = index_start + MAIN_DESCRIPTOR['size_main_sec'][index_size]
                    add2 = add + self.read_add(bitstream, index_start, index_end) -1
                    cv_logger.info("MAIN_END_ADD[%d]: 0x%08x"% (main_sec, add2))
                    fw_info["MAIN_END_ADD"].append(add2)

        if (single_image_rpd == 0):
            fw_info["END_ADD"] = fw_info["MAIN_END_ADD"][fw_info["MAIN_SEC_NUM"]]
            cv_logger.info("END_ADD: 0x%x"% fw_info["END_ADD"])

        # SSBL/TSBL start add
        index_start     = bitstream_start + BOOTROM_DESCRIPTOR['ssbl_offset'][index_offset]
        index_end       = index_start + BOOTROM_DESCRIPTOR['ssbl_offset'][index_size]
        fw_info["SSBL_START_ADD"] = bitstream_start + self.read_add( bitstream, index_start, index_end) + bitstream_flash_offset
        cv_logger.info("%s_START_ADD: 0x%08x"% (self.SSBL_TSBL,fw_info["SSBL_START_ADD"]))

        # SSBL/TSBL end address
        index_start     = bitstream_start + BOOTROM_DESCRIPTOR['ssbl_size'][index_offset]
        index_end       = index_start + BOOTROM_DESCRIPTOR['ssbl_size'][index_size]
        fw_info["SSBL_END_ADD"] = fw_info["SSBL_START_ADD"] + self.read_add( bitstream, index_start, index_end)
        cv_logger.info("%s_END_ADD: 0x%08x"% (self.SSBL_TSBL,fw_info["SSBL_END_ADD"]))

        # Trampoline start add
        index_start     = bitstream_start + CMF_DESCRIPTOR['offset_trampol'][index_offset]
        index_end       = index_start + CMF_DESCRIPTOR['offset_trampol'][index_size]
        fw_info["TRAMPOLINE_START_ADD"] = bitstream_start + self.read_add( bitstream, index_start, index_end) + bitstream_flash_offset
        cv_logger.info("TRAMPOLINE_START_ADD: 0x%08x"% fw_info["TRAMPOLINE_START_ADD"])

        # Trampoline end address
        index_start     = bitstream_start + CMF_DESCRIPTOR['size_trampoline'][index_offset]
        index_end       = index_start + CMF_DESCRIPTOR['size_trampoline'][index_size]
        fw_info["TRAMPOLINE_END_ADD"] = fw_info["TRAMPOLINE_START_ADD"] + self.read_add( bitstream, index_start, index_end)
        cv_logger.info("TRAMPOLINE_END_ADD: 0x%08x"% fw_info["TRAMPOLINE_END_ADD"])

        # Sync start add
        fw_info["SYNC_START_ADD"]=fw_info["TRAMPOLINE_END_ADD"]
        if fw_info["SYNC_START_ADD"]!=fw_info["SSBL_START_ADD"]:
            cv_logger.info("SYNC_START_ADD: 0x%08x"% fw_info["SYNC_START_ADD"])

            # Sync end address
            fw_info["SYNC_END_ADD"]=fw_info["SSBL_START_ADD"] - 1
            cv_logger.info("SYNC_END_ADD: 0x%08x"% fw_info["SYNC_END_ADD"])
        else:
            cv_logger.info("No Sync Block")


        return fw_info

    '''
    Require  :  rpd_get_rsu_fw_add() must be called beforehand
    Input    :  bitstream -- the bytearray of the read bitstream
                location -- "first4k", -- randomly select addr at first 4KB (cmf descriptor)
                           "signature_desc", randomly select addr at signature descriptor
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
                dcmf -- which dcmf copy to corrupt, default 1
                image -- "FACTORY"
                            "P1"
                            "P2"
                            "P3"
                            other -- for updated image
                updated_fw_info -- fw information for updated image
    Output   : returns a randomly selected address in the given location
    '''

    def select_addr(self, location, dcmf=1, image="FACTORY", updated_fw_info=None):
        random.seed()
        offset = None

        if ( image == "FACTORY" ):
            assert_err(hasattr(self, 'FACTORY'), "ERROR :: self.FACTORY is unknown")
            fw_info = self.FACTORY
        elif ( image == "P1" ):
            assert_err(hasattr(self, 'P1'), "ERROR :: self.P1 is unknown")
            fw_info = self.P1
        elif ( image == "P2" ):
            assert_err(hasattr(self, 'P2'), "ERROR :: self.P2 is unknown")
            fw_info = self.P2
        elif ( image == "P3" ):
            assert_err(hasattr(self, 'P3'), "ERROR :: self.P3 is unknown")
            fw_info = self.P3
        else:
            if updated_fw_info == None:
                assert_err(0, "ERROR :: select_addr without known image, must have updated_fw_info assigned. Please check your test")
            fw_info = updated_fw_info

        # cpb0_magicnumber
        if ( re.search( r'cpb', location) ):
            searchObj = re.search( r'cpb([0-1])_(\w*)', location)
            if searchObj:
                cpb_index = searchObj.group(1)
                if ( int(cpb_index) == 0 ) :
                    start_add = self.CPB0_START_ADD
                else:
                    start_add = self.CPB1_START_ADD

                cpb_location = searchObj.group(2)
                offset = start_add + CPB_DESC[cpb_location][0]
            else:
                assert_err(0, "ERROR :: Unsupport item %s" %location )

            cv_logger.info("Selected 0x%08x for %s" %(offset, location))


        elif ( re.search( r'spt', location) ):
            searchObj = re.search( r'spt([0-1])_(\w*)', location)
            if searchObj:
                spt_index = searchObj.group(1)
                if ( int(spt_index) == 0 ) :
                    start_add = self.SPT0_START_ADD
                else:
                    start_add = self.SPT1_START_ADD

                spt_location = searchObj.group(2)
                offset = start_add + SPT_DESC[spt_location][0]
            else:
                assert_err(0, "ERROR :: Unsupport item %s" %location )

            cv_logger.info("Selected 0x%08x for %s" %(offset, location))

        elif ( location == "first4k" ) :
            start   = fw_info["ABSOLUTE_START_ADD"] + 0
            end     = fw_info["ABSOLUTE_START_ADD"] + 4*1024 - 1
            offset = random.randint(start, end)
            cv_logger.info("Selected at first 4k randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "signature_desc" ) :
            start   = fw_info["ABSOLUTE_START_ADD"] + 1024*4
            end     = fw_info["ABSOLUTE_START_ADD"] + 1024*4 + 47
            offset = random.randint(start, end)
            cv_logger.info("Selected at signature_desc randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "ssbl" ) :
            start   = fw_info["SSBL_START_ADD"]
            end     = fw_info["SSBL_END_ADD"]
            offset = random.randint(start, end)
            cv_logger.info("Selected at %s randomly from 0x%08x to 0x%08x" %(self.SSBL_TSBL,start, end))

        elif ( location == "trampoline" ) :
            start   = fw_info["TRAMPOLINE_START_ADD"]
            end     = fw_info["TRAMPOLINE_END_ADD"]
            offset = random.randint(start, end)
            cv_logger.info("Selected at trampoline randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "sync_first_word" ) :
            start   = fw_info["SYNC_START_ADD"]
            end     = fw_info["SYNC_START_ADD"]+3
            offset = random.randint(start, end)
            cv_logger.info("Selected at sync first word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "sync_middle_word" ) :
            start   = fw_info["SYNC_START_ADD"]+4
            end     = fw_info["SYNC_END_ADD"]-4
            offset = random.randint(start, end)
            cv_logger.info("Selected at sync middle word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "sync_last_word" ) :
            start   = fw_info["SYNC_END_ADD"]-3
            end     = fw_info["SYNC_END_ADD"]
            offset = random.randint(start, end)
            cv_logger.info("Selected at sync last word randomly from 0x%08x to 0x%08x" %(start, end))

        elif ( location == "last" ) :
            # start   = 0
            # end     = len(bitstream)
            # offset  = len(bitstream)-1
            offset = fw_info["END_ADD"]
            cv_logger.info("Selected last byte - 0x%08x " %offset)

        elif ( location == "mbr" ) :
            start   = self.MBR_START_ADD
            end     = self.MBR_INFO_END_ADD
            # MBR signature 0x55AA is located at address of 510,511 in MBR partition
            offset = 510
            cv_logger.info("Change value of 0x%08x in mbr partition" %(offset))


        else:
            searchObj = re.search( r'main([1-4])_(desc|data)', location)
            if searchObj:
                # cv_logger.debug("main ", searchObj.group(1))
                main_index = searchObj.group(1)
                max_main = len(fw_info["MAIN_START_ADD"]) - 1
                assert_err ( int(main_index) <= max_main,
                    "ERROR :: Selected Section %s is out of range, Max Main Section is %d" % (main_index, max_main) )
                if ( searchObj.group(2) == "desc" ):
                    start = fw_info["MAIN_START_ADD"][int(main_index)]
                    end = fw_info["MAIN_START_ADD"][int(main_index)] + 0xFFF

                    main_offset_list = []
                    for each in MAIN_DESCRIPTOR:
                        if MAIN_DESCRIPTOR[each][2] == 1:
                            main_offset_list.append(MAIN_DESCRIPTOR[each][0])

                    random_ith = random.randint(0,len(main_offset_list)-1)
                    offset = fw_info["MAIN_START_ADD"][int(main_index)] + main_offset_list[random_ith]
                    cv_logger.info("Selected at Main %s Descriptor, with Main %s address 0x%08x, randomly from 0 to 0x1000" % (main_index, main_index, fw_info["MAIN_START_ADD"][int(main_index)]))

                else:
                    start = fw_info["MAIN_START_ADD"][int(main_index)] + 0x2000
                    if ( int(main_index) == max_main) :
                        end = fw_info["MAIN_END_ADD"][int(main_index)]
                    else:
                        end = fw_info["MAIN_START_ADD"][int(main_index)+1]-1
                    offset = random.randint(start, end)
                    cv_logger.info("Selected at Main %s Data, randomly from 0x%08x to 0x%08x" % (main_index, start, end))

            else:
                try:
                    # if location >=0 & :
                    searchObj = re.search( r'0x([0-9a-fA-F]*)', location)
                    if searchObj:
                        offset = int(location,16)
                    else:
                        offset = int(location)
                    # assert_err( offset < len(bitstream),
                        # "ERROR :: Unsupport item %s, offset larger than total bitstream 0x%08x" %(location,len(bitstream)) )
                    # else:
                        # assert_err(0, "ERROR :: Unsupport location item %s" %location )
                except:
                    assert_err(0, "ERROR :: Unsupport item %s" %location )
        #------SatyaS Added Code making address Byte Alligned----------#
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
            cv_logger.debug("Original Address selected by test ---> 0x%x" %offset)
            temp_offset = int(offset/4)
            offset      = temp_offset*4
            cv_logger.debug("Byte Alligned adjusted Address    ---> 0x%x" %offset)

        return offset

    '''
    Input    :  rpd_file_name - single image rpd to update
                start_address - QSPI address to write
                update -    1 for update mode that involved QSPI_ERASE;
                            0 for add to new flash offset that do not need QSPI_ERASE
                verify - Read back and verify the flash content
    Output   : returns status
    '''
    def add_new_image(self, rpd_file_name, start_address=0, update=True, verify=False) :

        status = True
        bitstream = self.read_bitstream(rpd_file_name)
        bitstream_size = len(bitstream)

        # 1. Erase
        if (update == 1):
            cv_logger.info("Erasing flash...")
            offset = 0
            while status and offset < bitstream_size :
                status = self.qspi.qspi_sector_erase(start_address + offset)
                offset +=  64<<10
        else:
            cv_logger.info("Skip QSPI_ERASE")

        # 2. Program
        if status :
            if os.environ.get("PYCV_PLATFORM") == 'simics' :
                cv_logger.info("Simics Programming %s..." % rpd_file_name)
                reserved_bitstream = bytearray()
                for data in bitstream :
                    if data == 0xFF or data == 0 :
                        reserved_bitstream.append(data)
                    else :
                        rdata = 0
                        for i in range(8) :
                            if data & (1 << i) :
                                rdata |= (1 << (7-i))
                        reserved_bitstream.append(rdata)
                self.qspi.prepare_data(reserved_bitstream, start_address, 30)
            else :
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
                        status = self.qspi.qspi_write(start_address + offset, *data_words)
                    offset += bytes_to_pgm
            cv_logger.info("Programming completed")

        # 3. Verify
        if status and verify and os.environ.get("PYCV_PLATFORM") != 'simics' :
            status = self.qspi.qspi_verify(rpd_file_name, start_address)

        return status



    '''
    Require  :  get_fw_add() must be called beforehand
    Input    :  bitstream -- the bytearray of the read bitstream
                location -- "first4k", -- randomly select addr at first 4KB (cmf descriptor)
                           "signature_desc", randomly select addr at signature descriptor
                           "hash_ssbl"          : BOOTROM_DESCRIPTOR["hash_ssbl"][0]
                           "hash_trampoline"    : CMF_DESCRIPTOR["hash_trampoline"][0]
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
                cmf_copy -- I am not sure what is this for, need to ask Bee Ling
    Output   : returns a randomly selected address in the given location
    '''

    def select_addr_rbf(self, bitstream, location, cmf_copy=1, mult_byte=0):
        return super(QspiTest, self).select_addr(bitstream, location, cmf_copy, mult_byte)

    '''
    Input     : bitstream --  bytearray of the bitstream
    Output    : returns fw_key for currently loaded fw, the key id used for the firmware signing
    '''
    def rsu_get_fw_key_by_bitstream(self, bitstream, image="P1"):

        cv_logger.info("Bitstream processing to get firmware key ID from RSU target image: %s"%image)

        if ( image == "FACTORY" ):
            assert_err(hasattr(self, 'FACTORY'), "ERROR :: self.FACTORY is unknown")
            fw_info = self.FACTORY
        elif ( image == "P1" ):
            assert_err(hasattr(self, 'P1'), "ERROR :: self.P1 is unknown")
            fw_info = self.P1
        elif ( image == "P2" ):
            assert_err(hasattr(self, 'P2'), "ERROR :: self.P2 is unknown")
            fw_info = self.P2
        elif ( image == "P3" ):
            assert_err(hasattr(self, 'P3'), "ERROR :: self.P3 is unknown")
            fw_info = self.P3
        else:
            assert_err(0, "ERROR :: rsu_get_fw_key_by_bitstream without a known image")

        # Check the signature block - after 4k
        index_signature   = fw_info["START_ADD"] + 0x1000

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