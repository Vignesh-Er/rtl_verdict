`timescale 1ns/1ps
module tb_fifo;
    reg clk = 0;
    reg rst_n = 0;
    reg wr_en = 0;
    reg [7:0] wr_data = 0;
    reg rd_en = 0;
    wire [7:0] rd_data;
    wire full, empty;

    fifo dut (.clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data), .rd_en(rd_en),
              .rd_data(rd_data), .full(full), .empty(empty));

    always #5 clk = ~clk;

    task check(input cond, input [255:0] msg, input integer cycle);
        begin
            if (!cond) begin
                $display("RTLVERDICT_RESULT: FAIL at cycle %0d: %0s", cycle, msg);
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
        check(empty == 1'b1 && full == 1'b0, "not empty after reset", 0);

        // write 5 values, verify empty clears and no overflow
        for (i = 0; i < 5; i = i + 1) begin
            wr_en = 1;
            wr_data = 8'h10 + i;
            @(negedge clk);
        end
        wr_en = 0;
        check(empty == 1'b0, "empty still asserted after writes", 5);
        check(full == 1'b0, "full wrongly asserted (depth=8, only 5 written)", 5);

        // read back 5 values, verify FIFO order (first written == first read).
        // rd_data is registered: pulse rd_en for exactly one cycle, then wait
        // one more cycle for rd_data to update before checking.
        for (i = 0; i < 5; i = i + 1) begin
            rd_en = 1;
            @(negedge clk);
            rd_en = 0;
            @(negedge clk);
            check(rd_data == (8'h10 + i), "read data out of FIFO order", 10 + i);
        end

        @(negedge clk);
        check(empty == 1'b1, "not empty after draining all writes", 20);

        // fill to full (8 entries), verify full asserts and further writes are ignored
        for (i = 0; i < 8; i = i + 1) begin
            wr_en = 1;
            wr_data = 8'hA0 + i;
            @(negedge clk);
        end
        wr_en = 0;
        check(full == 1'b1, "full not asserted after filling depth entries", 30);

        $display("RTLVERDICT_RESULT: PASS");
        $finish;
    end

    initial begin
        #3000;
        $display("RTLVERDICT_RESULT: FAIL at cycle unknown: timeout, testbench did not finish");
        $finish;
    end
endmodule
