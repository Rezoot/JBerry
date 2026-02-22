import ctypes
import os
import sys

# --- 1. C++ STRUCTURE DEFINITIONS ---

class ddTableDeal(ctypes.Structure):
    # Binary structure: cards[4][4] (Player, Suit)
    # unsigned int cards[4][4] represents bitmasks for cards held
    _fields_ = [("cards", ctypes.c_uint * 4 * 4)]

class ddTableResults(ctypes.Structure):
    # resTable[5][4] -> [Strain][Player]
    # Strains: 0=Spades, 1=Hearts, 2=Diamonds, 3=Clubs, 4=NT
    _fields_ = [("resTable", ctypes.c_int * 4 * 5)]

class parResults(ctypes.Structure):
    # Structure for PAR (Min-Max) results
    # parScore: Text representation of the score (e.g., "NS 2220")
    # parContractsString: Text representation of the contract (e.g., "NS 7NT")
    _fields_ = [
        ("parScore", (ctypes.c_char * 16) * 2),
        ("parContractsString", (ctypes.c_char * 128) * 2)
    ]

# --- 2. SOLVER CLASS ---

class BridgeSolver:
    def __init__(self, library_path="./libdds.so"):
        # Check if the library file exists
        if not os.path.exists(library_path):
            print(f"ERROR: Library not found at {library_path}")
            sys.exit(1)

        # Load the C++ shared library
        try:
            self.lib = ctypes.CDLL(os.path.abspath(library_path))
        except OSError as e:
            print(f"ERROR loading library: {e}")
            sys.exit(1)

        # --- Configure C++ Function Arguments ---
        
        # SetMaxThreads(int userThreads)
        self.lib.SetMaxThreads.argtypes = [ctypes.c_int]
        
        # CalcDDtable(ddTableDeal tableDeal, ddTableResults *tablep)
        self.lib.CalcDDtable.argtypes = [ddTableDeal, ctypes.POINTER(ddTableResults)]
        self.lib.CalcDDtable.restype = ctypes.c_int
        
        # Par(ddTableResults *tablep, parResults *presp, int vulnerable)
        self.lib.Par.argtypes = [ctypes.POINTER(ddTableResults), ctypes.POINTER(parResults), ctypes.c_int]
        self.lib.Par.restype = ctypes.c_int

        # Initialize threads (0 = auto-detect hardware concurrency)
        self.lib.SetMaxThreads(0)

        # --- Mappings ---
        # Suit Order in DDS: Spades=0, Hearts=1, Diamonds=2, Clubs=3
        self.SuitMap = {'S': 0, 'H': 1, 'D': 2, 'C': 3}
        self.HandMap = {'N': 0, 'E': 1, 'S': 2, 'W': 3}
        
        # Bitwise values for ranks (2 = bit 2 ... Ace = bit 14)
        self.RankMap = {
            '2': 1<<2, '3': 1<<3, '4': 1<<4, '5': 1<<5, 
            '6': 1<<6, '7': 1<<7, '8': 1<<8, '9': 1<<9, 
            'T': 1<<10, 'J': 1<<11, 'Q': 1<<12, 'K': 1<<13, 'A': 1<<14
        }

    def _format_contract(self, raw_bytes_array):
        """
        Helper: Extracts string from ctypes array and removes 'NS:' or 'EW:' prefixes.
        """
        # FIX: Added .value to access the byte string inside the ctypes array
        s = raw_bytes_array.value.decode('utf-8')
        
        if ':' in s:
            return s.split(':')[1] # Return the part after the colon
        return s

    def get_vulnerability(self, round):
        """
        Determine vulnerability based on the round number (Standard Bridge 16-board cycle).
        Mapping: 0 = None, 1 = NS, 2 = EW, 3 = Both
        """
        # Sekwencja założeń dla rozdań 1-16:
        # 1:None, 2:NS, 3:EW, 4:Both, 5:NS, 6:EW, 7:Both, 8:None... itd.
        vul_pattern = [0, 1, 2, 3, 1, 2, 3, 0, 2, 3, 0, 1, 3, 0, 1, 2]
    
        # Zwraca wartość dla danego rozdania (modulo 16 obsługuje rozdania > 16)
        return vul_pattern[(round - 1) % 16]

    def solve_debug_console(self, hands_dict, round):
        """
        Main function to solve the deal.
        Input: hands_dict = {'N': ['AS', 'KS'...], 'E': [...], ...}
        """
        deal = ddTableDeal()

        # 1. Convert Python List -> C++ Bitmasks
        total_cards = 0
        for player, cards in hands_dict.items():
            if player not in self.HandMap: continue
            p_idx = self.HandMap[player]

            for card in cards:
                if len(card) < 2: continue
                
                # Input format expected: 'AS' -> Rank='A', Suit='S'
                rank_char = card[0].upper()
                suit_char = card[1].upper()

                if rank_char in self.RankMap and suit_char in self.SuitMap:
                    bit = self.RankMap[rank_char]
                    suit_idx = self.SuitMap[suit_char]
                    
                    # Apply bitwise OR to add the card to the hand
                    deal.cards[p_idx][suit_idx] |= bit
                    total_cards += 1

        # Validation
        if total_cards != 52:
            print(f"WARNING: Input contains {total_cards} cards instead of 52! Results may be invalid.")

        # 2. Calculate Double Dummy Table
        table = ddTableResults()
        res = self.lib.CalcDDtable(deal, ctypes.byref(table))

        if res != 1:
            print(f"DDS Calculation Error, code: {res}")
            return

        # 3. Display DD Table
        print("\n--- Double Dummy Analysis ---")
        print("-------------------------------------------------")
        print("|  Strain  | North | South |  East |  West  |")
        print("|----------+-------+-------+-------+--------|")
        
        suits_str = ["Pik", "Kier", "Karo", "Trefl", "NT"] # Polish names kept for display
        # Display Order: NT(4), S(0), H(1), D(2), C(3)
        display_order = [4, 0, 1, 2, 3]

        for s_idx in display_order:
            row_name = suits_str[s_idx] if s_idx < 5 else "?"
            
            # Retrieve tricks for each player
            val_n = table.resTable[s_idx][0]
            val_e = table.resTable[s_idx][1]
            val_s = table.resTable[s_idx][2]
            val_w = table.resTable[s_idx][3]
            
            # Format output table
            print(f"| {row_name:<8} |   {val_n:2}  |   {val_s:2}  |   {val_e:2}  |   {val_w:2}  |")
        
        print("-------------------------------------------------")

        # 4. Calculate PAR (Min-Max Score)
        pres = parResults()
        vulnerability = self.vulnerability(round) # 0=none, 1=NS, 2=EW, 3=both
        vuln_str = ["None", "NS", "EW", "Both"][vulnerability]

        res = self.lib.Par(ctypes.byref(table), ctypes.byref(pres), vulnerability)

        if res == 1:
            # FIX: Added .value to access bytes before decoding
            contract = self._format_contract(pres.parContractsString[0])
            score = pres.parScore[0].value.decode('utf-8')
            
            print("\n=== PAR RESULT (MIN-MAX) ===")
            print(f"vulnerability: {vuln_str}")
            print(f"Optimal Contract: {contract}")
            print(f"Score:            {score}")
        else:
            print(f"PAR Calculation Error, code: {res}")



    def solve(self, hands_dict, round_num):
        """
        Main function to solve the deal.
        Returns a consistent dictionary structure regardless of success or failure.
        """
        # 1. Inicjalizacja domyślnej struktury odpowiedzi
        result_data = {
            "status": "error",
            "message": "",
            "dd_table": {},
            "par_result": {
                "vulnerability": "Unknown",
                "optimal_contract": "-",
                "score": "0"
            }
        }

        try:
            deal = ddTableDeal()
            # Inicjalizacja macierzy zerami
            deal.cards = ((ctypes.c_uint * 4) * 4)() 

            # 2. Konwersja Python List -> C++ Bitmasks
            total_cards = 0
            for player, cards in hands_dict.items():
                if player not in self.HandMap: continue
                p_idx = self.HandMap[player]

                for card in cards:
                    if len(card) < 2: continue
                    rank_char = card[0].upper()
                    suit_char = card[1].upper()

                    if rank_char in self.RankMap and suit_char in self.SuitMap:
                        bit = self.RankMap[rank_char]
                        suit_idx = self.SuitMap[suit_char]
                        deal.cards[p_idx][suit_idx] |= bit
                        total_cards += 1

            if total_cards != 52:
                result_data["message"] = f"Invalid card count: {total_cards}"
                return result_data

            # 3. Obliczenia Double Dummy (CalcDDtable)
            table = ddTableResults()
            res_dd = self.lib.CalcDDtable(deal, ctypes.byref(table))

            if res_dd != 1:
                result_data["message"] = f"DDS CalcDDtable Error: {res_dd}"
                return result_data

            # 4. Obliczenia PAR (Par)
            pres = parResults()
            # Pobieramy vulnerability (0-3) używając poprawionej wcześniej metody
            vul_val = self.get_vulnerability(round_num) 
            vuln_str = ["None", "NS", "EW", "Both"][vul_val]

            res_par = self.lib.Par(ctypes.byref(table), ctypes.byref(pres), vul_val)

            contract = "-"
            score = "0"

            if res_par == 1:
                # --- KLUCZOWA POPRAWKA ---
                # Używamy .value, aby pobrać ciąg bajtów z tablicy C do null-terminatora
                try:
                    # pres.parContractsString to tablica c_char, .value zwraca bytes
                    contract = self._format_contract(pres.parContractsString[0])
                    score = pres.parScore[0].value.decode('utf-8')
                except Exception as decode_err:
                    contract = f"Decode Error: {decode_err}"
            else:
                result_data["message"] = f"DDS Par Error: {res_par}"

            # 5. Budowanie ostatecznej odpowiedzi
            suits_str = ["Pik", "Kier", "Karo", "Trefl", "NT"]
            display_order = [4, 0, 1, 2, 3] # NT, S, H, D, C

            structured_dd = {}
            for s_idx in display_order:
                suit_name = suits_str[s_idx]
                structured_dd[suit_name] = {
                    "N": table.resTable[s_idx][0],
                    "E": table.resTable[s_idx][1],
                    "S": table.resTable[s_idx][2],
                    "W": table.resTable[s_idx][3],
                }

            # Sukces - nadpisujemy dane
            result_data["status"] = "ok"
            result_data["dd_table"] = structured_dd
            result_data["par_result"] = {
                "vulnerability": vuln_str,
                "optimal_contract": contract,
                "score": score
            }

        except Exception as e:
            result_data["message"] = f"Python Exception: {str(e)}"
        
        return result_data