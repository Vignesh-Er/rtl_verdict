`timescale 1ns/1ps
module tb_uart;
    reg clk = 0;
    reg rst_n = 0;
    reg tx_start = 0;
    reg [7:0] tx_data = 0;
    wire tx, tx_busy;

    uart dut (.clk(clk), .rst_n(rst_n), .tx_start(tx_start), .tx_data(tx_data), .tx(tx), .tx_busy(tx_busy));

    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("tb_uart.vcd");
            $dumpvars(0, tb_uart);
        end
    end

    always #5 clk = ~clk;

    integer errors = 0;
    reg [9:0] captured; // start(1) + data(8) + stop(1), captured LSB-first as bits arrive
    integer bitcount;

    task check(input cond, input [255:0] msg, input integer cycle);
        begin
            if (!cond) begin
                $display("RTLVERDICT_RESULT: FAIL at cycle %0d: %0s", cycle, msg);
                errors = errors + 1;
                $finish;
            end
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        @(negedge clk);
        check(tx == 1'b1 && tx_busy == 1'b0, "line not idle-high after reset", 0);

        tx_data = 8'hA5;
        tx_start = 1;
        @(negedge clk);
        tx_start = 0;
        check(tx_busy == 1'b1, "tx_busy not asserted after start", 1);

        // start bit
        @(negedge clk);
        check(tx == 1'b0, "start bit not driven low", 2);

        // 8 data bits, LSB first per RTL (shift_reg[bit_index])
        for (bitcount = 0; bitcount < 8; bitcount = bitcount + 1) begin
            @(negedge clk);
            check(tx == tx_data[bitcount], "data bit mismatch", 3 + bitcount);
        end

        // stop bit
        @(negedge clk);
        check(tx == 1'b1, "stop bit not driven high", 11);
        check(tx_busy == 1'b0, "tx_busy not cleared after stop bit", 11);

        $display("RTLVERDICT_RESULT: PASS");
        $finish;
    end

    initial begin
        #2000;
        $display("RTLVERDICT_RESULT: FAIL at cycle unknown: timeout, testbench did not finish");
        $finish;
    end
endmodule
