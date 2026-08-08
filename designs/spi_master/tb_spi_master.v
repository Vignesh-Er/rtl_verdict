`timescale 1ns/1ps
module tb_spi_master;
    reg clk = 0;
    reg rst_n = 0;
    reg start = 0;
    reg [7:0] tx_data = 0;
    wire sclk, cs_n, mosi, busy;

    spi_master dut (.clk(clk), .rst_n(rst_n), .start(start), .tx_data(tx_data),
                     .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .busy(busy));

    always #5 clk = ~clk;

    integer errors = 0;

    task check(input cond, input [255:0] msg, input integer cycle);
        begin
            if (!cond) begin
                $display("RTLVERDICT_RESULT: FAIL at cycle %0d: %0s", cycle, msg);
                errors = errors + 1;
                $finish;
            end
        end
    endtask

    integer i;
    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        @(negedge clk);
        check(cs_n == 1'b1 && busy == 1'b0, "not idle after reset", 0);

        tx_data = 8'h3C;
        start = 1;
        @(negedge clk);
        start = 0;
        check(busy == 1'b1 && cs_n == 1'b0, "busy/cs_n not asserted after start", 1);

        // wait up to 40 cycles for transaction to complete (8 bits x ~2 sclk toggles each + margin)
        for (i = 0; i < 40; i = i + 1) begin
            @(negedge clk);
            if (!busy) i = 100;
        end
        check(busy == 1'b0, "transaction never completed", 40);
        check(cs_n == 1'b1, "cs_n not deasserted after completion", 40);

        $display("RTLVERDICT_RESULT: PASS");
        $finish;
    end

    initial begin
        #2000;
        $display("RTLVERDICT_RESULT: FAIL at cycle unknown: timeout, testbench did not finish");
        $finish;
    end
endmodule
